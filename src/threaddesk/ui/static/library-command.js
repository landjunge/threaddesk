document.querySelector("[data-library-speak]")?.addEventListener("click", () => {
  const button = document.querySelector("[data-library-speak]");
  const note = document.querySelector("[data-library-speech]");
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    note.textContent = button.dataset.unavailable;
    return;
  }
  if (!window.isSecureContext) {
    note.textContent = button.dataset.insecure;
    return;
  }
  const recognition = new Recognition();
  recognition.lang = document.body.dataset.language === "en" ? "en-US" : "de-DE";
  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript.trim();
    const input = document.querySelector("[data-library-command]");
    input.value = transcript;
    if (transcript) input.form.requestSubmit();
  };
  recognition.onerror = (event) => {
    if (event.error === "not-allowed") note.textContent = button.dataset.denied;
    else if (event.error === "no-speech") note.textContent = button.dataset.silent;
    else note.textContent = button.dataset.unavailable;
  };
  recognition.start();
});
