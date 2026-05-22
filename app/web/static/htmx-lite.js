function openDialog(selector) {
  const dialog = selector ? document.querySelector(selector) : null;
  if (dialog && typeof dialog.showModal === "function" && !dialog.open) {
    dialog.showModal();
  }
}

function closeDialog(button) {
  const dialog = button.closest("dialog");
  if (dialog) {
    dialog.close();
  }
}

function emptyInputs(row) {
  row.querySelectorAll("input").forEach((input) => {
    input.value = "";
    input.required = false;
  });
}

function addBracketRow(button) {
  const editor = button.closest("[data-bracket-editor]");
  const tbody = editor ? editor.querySelector("tbody") : null;
  const lastRow = tbody ? tbody.querySelector("tr:last-child") : null;
  if (!tbody || !lastRow) return;

  const row = lastRow.cloneNode(true);
  emptyInputs(row);
  tbody.appendChild(row);
}

function removeBracketRow(button) {
  const tbody = button.closest("tbody");
  const row = button.closest("tr");
  if (!tbody || !row || tbody.querySelectorAll("tr").length <= 1) return;
  row.remove();
}

document.addEventListener("click", async (event) => {
  const closeButton = event.target.closest("[data-dialog-close]");
  if (closeButton) {
    closeDialog(closeButton);
    return;
  }

  const addButton = event.target.closest("[data-add-bracket]");
  if (addButton) {
    addBracketRow(addButton);
    return;
  }

  const removeButton = event.target.closest("[data-remove-bracket]");
  if (removeButton) {
    removeBracketRow(removeButton);
    return;
  }

  const trigger = event.target.closest("[hx-get]");
  if (!trigger) return;

  event.preventDefault();
  const targetSelector = trigger.getAttribute("hx-target");
  const target = targetSelector ? document.querySelector(targetSelector) : null;
  if (!target) return;

  target.innerHTML = `<div class="empty">Загрузка детализации</div>`;
  openDialog(trigger.getAttribute("hx-dialog"));
  trigger.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(trigger.getAttribute("hx-get"), {
      headers: { "HX-Request": "true" },
    });
    if (!response.ok) {
      target.innerHTML = `<div class="empty">Не удалось загрузить детализацию</div>`;
      return;
    }
    target.innerHTML = await response.text();
  } finally {
    trigger.removeAttribute("aria-busy");
  }
});

document.addEventListener("click", (event) => {
  if (event.target instanceof HTMLDialogElement) {
    event.target.close();
  }
});
