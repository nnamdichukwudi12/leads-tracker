document.addEventListener('DOMContentLoaded', function () {
  const demoLogin = document.getElementById('demo-login');
  const modal = document.getElementById('login-modal');
  const closeModal = document.getElementById('close-modal');
  const closeButton = document.getElementById('close-modal-action');
  const searchForm = document.getElementById('index-search-form');
  const resultBox = document.getElementById('index-search-result');

  function openModal() {
    modal.setAttribute('aria-hidden', 'false');
    modal.classList.add('modal-open');
  }

  function closeModalAction() {
    modal.setAttribute('aria-hidden', 'true');
    modal.classList.remove('modal-open');
  }

  demoLogin?.addEventListener('click', openModal);
  closeModal?.addEventListener('click', closeModalAction);
  closeButton?.addEventListener('click', closeModalAction);

  searchForm?.addEventListener('submit', function(event) {
    event.preventDefault();
    resultBox.textContent = 'This is a demo preview. The full app login requires backend deployment.';
  });
});
