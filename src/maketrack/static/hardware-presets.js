/* Hardware-preset autocomplete.
 *
 * Wires every <input data-hardware-preset="<unit-field-name>"> on the page
 * to a generated <datalist> populated from /static/hardware-presets.json,
 * and prefills the linked unit field when a recognized preset is chosen
 * (only when that unit field is empty — never overwrites the user's value).
 *
 * Self-skipping: if no inputs declare data-hardware-preset, the JSON fetch
 * never fires.
 */
(function () {
  function init() {
    const targets = document.querySelectorAll('input[data-hardware-preset]');
    if (targets.length === 0) return;

    fetch('/static/hardware-presets.json')
      .then((r) => r.json())
      .then((data) => {
        const presets = (data && data.presets) || [];
        const byName = new Map(presets.map((p) => [p.name, p]));

        // One shared datalist for the whole page — all inputs link to it.
        const datalist = document.createElement('datalist');
        datalist.id = 'maketrack-hardware-presets';
        for (const p of presets) {
          const opt = document.createElement('option');
          opt.value = p.name;
          datalist.appendChild(opt);
        }
        document.body.appendChild(datalist);

        targets.forEach((input) => {
          input.setAttribute('list', datalist.id);
          const unitFieldName = input.dataset.hardwarePreset;
          input.addEventListener('input', () => {
            const preset = byName.get(input.value);
            if (!preset || !input.form) return;
            const unitInput = input.form.querySelector(
              'input[name="' + unitFieldName + '"]'
            );
            // Only fill if the unit field is empty so we never clobber a
            // value the user typed manually.
            if (unitInput && !unitInput.value) {
              unitInput.value = preset.unit || '';
            }
          });
        });
      })
      .catch(() => {
        /* swallow — autocomplete is a nice-to-have, not load-bearing */
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
