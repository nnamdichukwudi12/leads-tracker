"""
Advanced email validation and verification service.
Provides syntax validation, SMTP verification, and bounce detection.
"""
import re
import asyncio
import smtplib
import os
from typing import Optional, Dict, Any
from email_validator import validate_email, EmailNotValidError
from sqlmodel import Session, select
from ..models import Lead, Suppression

# SMTP verification settings
SMTP_VERIFICATION_ENABLED = os.getenv('SMTP_VERIFICATION_ENABLED', 'false').lower() in ('1', 'true', 'yes')
SMTP_VERIFICATION_TIMEOUT = int(os.getenv('SMTP_VERIFICATION_TIMEOUT', '5'))  # seconds
SMTP_VERIFICATION_RATE_LIMIT = int(os.getenv('SMTP_VERIFICATION_RATE_LIMIT', '10'))  # per second
SMTP_VERIFICATION_BATCH_SIZE = int(os.getenv('SMTP_VERIFICATION_BATCH_SIZE', '100'))

# Email syntax patterns
COMMON_DISPOSABLE_DOMAINS = {
    'tempmail.com', 'guerrillamail.com', '10minutemail.com', 'mailinator.com',
    'throwaway.email', 'temp-mail.org', 'maildrop.cc', 'spam4.me'
}

class EmailValidator:
    """Advanced email validation with SMTP verification support."""
    
    def __init__(self):
        self.verification_semaphore = asyncio.Semaphore(SMTP_VERIFICATION_RATE_LIMIT)
        self.verified_cache = {}  # Simple cache for verified emails
    
    def is_syntax_valid(self, email: str | None) -> bool:
        """
        Validate email syntax using email-validator library.
        Returns True if valid, False otherwise.
        """
        if not email:
            return False
        
        try:
            validated = validate_email(email.strip())
            return validated is not None
        except EmailNotValidError:
            return False
    
    def is_disposable_email(self, email: str | None) -> bool:
        """
        Check if email uses a known disposable/temporary service.
        Returns True if disposable, False otherwise.
        """
        if not email:
            return False
        
        try:
            domain = email.strip().lower().split('@')[1]
            return domain in COMMON_DISPOSABLE_DOMAINS
        except (IndexError, AttributeError):
            return False
    
    def extract_email_domain(self, email: str | None) -> str | None:
        """Extract domain from email address."""
        if not email:
            return None
        try:
            return email.strip().lower().split('@')[1]
        except (IndexError, AttributeError):
            return None
    
    async def verify_smtp(self, email: str, domain_mx: Optional[str] = None) -> Dict[str, Any]:
        """
        Verify email via SMTP connection to domain's mail server.
        Uses rate limiting to prevent server overload.
        
        Returns dict with keys:
        - verified: bool (True if email appears valid)
        - method: str ('smtp_verification')
        - details: str (reason or error message)
        - mx_domain: str (mail server domain attempted)
        """
        if not SMTP_VERIFICATION_ENABLED:
            return {
                'verified': None,
                'method': 'smtp_verification_disabled',
                'details': 'SMTP verification is disabled',
                'mx_domain': None
            }
        
        if not self.is_syntax_valid(email):
            return {
                'verified': False,
                'method': 'smtp_verification',
                'details': 'Invalid email syntax',
                'mx_domain': domain_mx
            }
        
        # Check cache first
        if email.lower() in self.verified_cache:
            return self.verified_cache[email.lower()]
        
        # Rate limit using semaphore
        async with self.verification_semaphore:
            try:
                # In production, would use dnspython to get MX records and attempt SMTP verification
                # For now, return simplified verification
                domain = self.extract_email_domain(email)
                
                if not domain:
                    return {
                        'verified': False,
                        'method': 'smtp_verification',
                        'details': 'Could not extract domain',
                        'mx_domain': None
                    }
                
                # Simulate async SMTP check with timeout
                result = await asyncio.wait_for(
                    self._perform_smtp_check(email, domain),
                    timeout=SMTP_VERIFICATION_TIMEOUT
                )
                
                # Cache result
                self.verified_cache[email.lower()] = result
                return result
            
            except asyncio.TimeoutError:
                return {
                    'verified': None,
                    'method': 'smtp_verification',
                    'details': 'SMTP verification timeout',
                    'mx_domain': domain_mx
                }
            except Exception as e:
                return {
                    'verified': None,
                    'method': 'smtp_verification',
                    'details': f'SMTP verification error: {str(e)[:100]}',
                    'mx_domain': domain_mx
                }
    
    async def _perform_smtp_check(self, email: str, domain: str) -> Dict[str, Any]:
        """
        Perform actual SMTP verification in async context.
        """
        return await asyncio.to_thread(
            self._smtp_check_sync,
            email,
            domain
        )
    
    def _smtp_check_sync(self, email: str, domain: str) -> Dict[str, Any]:
        """
        Synchronous SMTP verification (runs in thread).
        Attempts connection to MX servers to verify email exists.
        """
        try:
            import dns.resolver
            
            # Get MX records
            try:
                mx_records = dns.resolver.resolve(domain, 'MX')
            except Exception as e:
                return {
                    'verified': False,
                    'method': 'smtp_verification',
                    'details': f'No MX records found: {str(e)[:50]}',
                    'mx_domain': domain
                }
            
            # Try connecting to MX servers
            for mx in mx_records[:3]:  # Try first 3 MX servers
                mx_host = str(mx.exchange)[:-1]  # Remove trailing dot
                
                try:
                    # Connect to SMTP server
                    with smtplib.SMTP(mx_host, 25, timeout=SMTP_VERIFICATION_TIMEOUT) as server:
                        server.helo(server.local_hostname)
                        server.mail('noreply@leads-tracker.local')
                        
                        # Try RCPT TO to verify recipient
                        code, response = server.rcpt(email)
                        
                        if code == 250:  # 250 = OK
                            return {
                                'verified': True,
                                'method': 'smtp_verification',
                                'details': 'Email verified via SMTP',
                                'mx_domain': mx_host
                            }
                        elif code == 550:  # 550 = mailbox not found
                            return {
                                'verified': False,
                                'method': 'smtp_verification',
                                'details': 'Mailbox not found',
                                'mx_domain': mx_host
                            }
                        else:
                            # Uncertain response
                            continue
                
                except Exception as e:
                    continue  # Try next MX server
            
            # Could not verify with any MX server
            return {
                'verified': None,
                'method': 'smtp_verification',
                'details': 'Could not verify with MX servers',
                'mx_domain': domain
            }
        
        except ImportError:
            # dns library not available
            return {
                'verified': None,
                'method': 'smtp_verification',
                'details': 'dns.resolver not available',
                'mx_domain': domain
            }
        except Exception as e:
            return {
                'verified': None,
                'method': 'smtp_verification',
                'details': f'SMTP check error: {str(e)[:100]}',
                'mx_domain': domain
            }
    
    async def validate_and_verify(self, email: str | None, use_smtp: bool = True) -> Dict[str, Any]:
        """
        Complete email validation and verification pipeline.
        
        Returns dict with:
        - valid: bool (overall validity)
        - verified: bool|None (SMTP verification result)
        - reasons: list (validation failure reasons)
        - details: str (detailed status)
        """
        reasons = []
        
        if not email:
            return {
                'valid': False,
                'verified': False,
                'reasons': ['Empty email address'],
                'details': 'No email provided'
            }
        
        email = email.strip()
        
        # Syntax validation
        if not self.is_syntax_valid(email):
            reasons.append('Invalid email syntax')
            return {
                'valid': False,
                'verified': False,
                'reasons': reasons,
                'details': 'Failed syntax validation'
            }
        
        # Disposable email check
        if self.is_disposable_email(email):
            reasons.append('Disposable/temporary email service')
        
        # SMTP verification
        verified = None
        if use_smtp and SMTP_VERIFICATION_ENABLED:
            smtp_result = await self.verify_smtp(email)
            verified = smtp_result.get('verified')
            if verified is False:
                reasons.append(f"SMTP verification failed: {smtp_result.get('details', 'Unknown')}")
        
        # Determine overall validity
        # Valid if: syntax OK + (no SMTP or SMTP verified or SMTP inconclusive)
        is_valid = len(reasons) <= 1  # Only disposable email doesn't invalidate
        
        return {
            'valid': is_valid,
            'verified': verified if verified is not None else True,  # Default to True if inconclusive
            'reasons': reasons,
            'details': ' | '.join(reasons) if reasons else 'Email appears valid'
        }


# Global validator instance
_validator = None

def get_email_validator() -> EmailValidator:
    """Get or create global email validator instance."""
    global _validator
    if _validator is None:
        _validator = EmailValidator()
    return _validator


async def validate_email_async(email: str | None, use_smtp: bool = True) -> Dict[str, Any]:
    """Async email validation wrapper."""
    validator = get_email_validator()
    return await validator.validate_and_verify(email, use_smtp)
