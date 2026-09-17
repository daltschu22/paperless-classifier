for (const id of ['login-form', 'token-form']) {
  document.getElementById(id).addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.target.querySelector('button');
    button.disabled = true;
    document.getElementById('login-error').textContent = '';
    try {
      const response = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Sign-in failed. Check your credentials.');
      window.location.assign('/');
    } catch(error) { document.getElementById('login-error').textContent = error.message; }
    finally { button.disabled = false; }
  });
}
