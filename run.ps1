# Run the app with local Python if available, otherwise fall back to Docker.
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    Write-Host "Found Python at $($python.Path). Installing dependencies and starting app..."
    & $python.Path -m pip install --upgrade pip
    & $python.Path -m pip install -r requirements.txt
    & $python.Path -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
    return
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    Write-Host "Python not found; falling back to Docker."
    docker build -t ai-leads-tracker .
    docker run --rm -p 8000:8000 -e DATABASE_URL=sqlite:///./leads.db -v ${PWD}:/app ai-leads-tracker
    return
}

Write-Host "No Python or Docker executable found. Install Python or Docker and try again." -ForegroundColor Red
