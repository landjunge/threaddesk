/* Form revisions always refer to the selected rendered source and target. */
document.addEventListener("change", event => {
  const select = event.target.closest('form[action="/knowledge/relations"] select');
  if (!select || !["source_id", "target_id"].includes(select.name)) return;
  const field = select.name === "source_id" ? "expected_revision" : "expected_target_revision";
  select.form.elements[field].value = select.selectedOptions[0]?.dataset.revision || "";
});
