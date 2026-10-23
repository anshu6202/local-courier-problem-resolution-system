document.addEventListener('DOMContentLoaded', () => {
  const statusField = document.querySelector('#id_status');
  const failureReasonField = document.querySelector('#id_failure_reason');
  const deliveredToField = document.querySelector('#id_delivered_to');
  const otpField = document.querySelector('#id_otp');

  const updateStatusFields = () => {
    if (!statusField) return;

    const selectedStatus = statusField.value;
    const conditionalFields = [
      [failureReasonField, selectedStatus === 'FAILED'],
      [deliveredToField, selectedStatus === 'DELIVERED'],
      [otpField, selectedStatus === 'DELIVERED'],
    ];

    conditionalFields.forEach(([field, shouldShow]) => {
      const wrapper = field?.closest('p');
      if (wrapper) wrapper.hidden = !shouldShow;
    });
  };

  statusField?.addEventListener('change', updateStatusFields);
  updateStatusFields();

  const selectAll = document.querySelector('[data-select-all]');
  selectAll?.addEventListener('change', () => {
    document
      .querySelectorAll('input[name="parcel_ids"][form="bulk-assignment"]')
      .forEach((checkbox) => {
        checkbox.checked = selectAll.checked;
      });
  });

  document.querySelectorAll('[data-filterable-list]').forEach((list) => {
    const rows = Array.from(list.querySelectorAll('tbody tr[data-status]'));
    const search = list.querySelector('[data-list-search]');
    const status = list.querySelector('[data-list-status]');
    const count = list.querySelector('[data-list-count]');
    const empty = list.querySelector('[data-filter-empty]');
    const unit = list.dataset.listUnit || 'records';
    let debounceTimer;

    const filterRows = () => {
      const term = (search?.value || '').trim().toLocaleLowerCase();
      const selectedStatus = status?.value || '';
      let visibleCount = 0;

      rows.forEach((row) => {
        const searchableText = (row.dataset.search || row.textContent).toLocaleLowerCase();
        const matches = searchableText.includes(term)
          && (!selectedStatus || row.dataset.status === selectedStatus);

        if (matches) {
          row.hidden = false;
          requestAnimationFrame(() => row.classList.remove('is-filtered-out'));
          visibleCount += 1;
        } else {
          row.classList.add('is-filtered-out');
          window.setTimeout(() => {
            if (row.classList.contains('is-filtered-out')) row.hidden = true;
          }, 170);
        }
      });

      if (count) {
        const countUnit = rows.length === 1 ? unit.replace(/s$/, '') : unit;
        count.textContent = `Showing ${visibleCount} of ${rows.length} ${countUnit}`;
      }
      if (empty) empty.hidden = visibleCount !== 0 || rows.length === 0;
    };

    search?.addEventListener('input', () => {
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(filterRows, 200);
    });
    status?.addEventListener('change', filterRows);
    filterRows();
  });

  document.querySelectorAll('[data-toast-dismiss]').forEach((button) => {
    button.addEventListener('click', () => button.closest('.alert')?.remove());
  });
});
