/* Loan Desk: pickup calendar, equipment search and asset filters. */

const SESSIONS = [
    { id: 'am', name: 'Morning', time: '8 AM to 12 PM', start: '08:00', end: '12:00' },
    { id: 'pm', name: 'Afternoon', time: '1 PM to 5 PM', start: '13:00', end: '17:00' },
    { id: 'day', name: 'All day', time: '8 AM to 5 PM', start: '08:00', end: '17:00' },
];

function manilaToday() {
    const now = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Manila' }));
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function isoDate(d) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function loanCalendar(pickup) {
    const start = pickup ? new Date(pickup) : manilaToday();
    const hour = start.getHours();
    return {
        sessions: SESSIONS,
        today: manilaToday(),
        selected: new Date(start.getFullYear(), start.getMonth(), start.getDate()),
        shown: new Date(start.getFullYear(), start.getMonth(), 1),
        session: hour >= 13 ? 'pm' : 'am',
        open: false,
        summary: '',
        init() { this.publish(); },
        get monthName() {
            return this.shown.toLocaleDateString('en-PH', { month: 'long', year: 'numeric' });
        },
        get blanks() { return Array.from({ length: this.shown.getDay() }, (_, i) => i); },
        get canGoBack() {
            return this.shown > new Date(this.today.getFullYear(), this.today.getMonth(), 1);
        },
        get days() {
            const year = this.shown.getFullYear();
            const month = this.shown.getMonth();
            const count = new Date(year, month + 1, 0).getDate();
            return Array.from({ length: count }, (_, i) => {
                const date = new Date(year, month, i + 1);
                const weekend = date.getDay() === 0 || date.getDay() === 6;
                return {
                    n: i + 1,
                    date,
                    off: weekend || date < this.today,
                    sel: date.getTime() === this.selected.getTime(),
                    label: date.toLocaleDateString('en-PH', { weekday: 'long', day: 'numeric', month: 'long' }),
                };
            });
        },
        move(step) {
            this.shown = new Date(this.shown.getFullYear(), this.shown.getMonth() + step, 1);
        },
        pick(day) {
            if (day.off) return;
            this.selected = day.date;
            this.apply();
        },
        choose(id) {
            this.session = id;
            this.open = false;
            this.apply();
        },
        apply() {
            this.publish();
            htmx.trigger(document.getElementById('availability-form'), 'submit');
        },
        publish() {
            const session = SESSIONS.find((s) => s.id === this.session);
            const day = isoDate(this.selected);
            document.getElementById('pickup-input').value = `${day}T${session.start}`;
            document.getElementById('return-input').value = `${day}T${session.end}`;
            const name = this.selected.toLocaleDateString('en-PH', { weekday: 'short', day: 'numeric', month: 'short' });
            window.loanWhen = `${name}, ${session.name.toLowerCase()}`;
            this.summary = `${name}, ${session.time}`;
            filterEquipment();
        },
    };
}

const equipmentFilter = { term: '', type: 'All', onlyFree: false };

function filterEquipment() {
    const rows = [...document.querySelectorAll('.desk-row')];
    if (!rows.length) return;
    const term = equipmentFilter.term.trim().toLowerCase();
    const matches = rows.filter((row) => (!term || row.dataset.search.includes(term))
        && (!equipmentFilter.onlyFree || Number(row.dataset.free) > 0));
    const types = ['All', ...new Set(rows.map((row) => row.dataset.type))];
    if (!types.includes(equipmentFilter.type)) equipmentFilter.type = 'All';
    const shown = matches.filter((row) => equipmentFilter.type === 'All' || row.dataset.type === equipmentFilter.type);
    rows.forEach((row) => { row.hidden = !shown.includes(row); });

    const tabs = document.getElementById('equipment-tabs');
    tabs.replaceChildren(...types.map((type) => {
        const button = document.createElement('button');
        const count = type === 'All' ? matches.length : matches.filter((row) => row.dataset.type === type).length;
        button.type = 'button';
        button.className = 'idx';
        button.setAttribute('aria-pressed', String(type === equipmentFilter.type));
        button.append(type.replace(/ Equipment$/, ''));
        const number = document.createElement('span');
        number.className = 'num';
        number.textContent = count;
        button.append(number);
        button.addEventListener('click', () => { equipmentFilter.type = type; filterEquipment(); });
        return button;
    }));

    document.querySelectorAll('[data-section]').forEach((section) => {
        section.hidden = !section.querySelector('.desk-row:not([hidden])');
    });
    const free = shown.filter((row) => Number(row.dataset.free) > 0).length;
    const heading = document.getElementById('equipment-heading');
    if (heading) heading.textContent = `${free} free ${window.loanWhen || ''}`.trim();
    document.getElementById('equipment-empty').hidden = shown.length > 0;
}

function resetEquipmentFilter() {
    equipmentFilter.term = '';
    equipmentFilter.type = 'All';
    equipmentFilter.onlyFree = false;
    document.getElementById('equipment-search').value = '';
    document.getElementById('equipment-free').checked = false;
    filterEquipment();
}

document.addEventListener('input', (event) => {
    if (event.target.id === 'equipment-search') {
        equipmentFilter.term = event.target.value;
        filterEquipment();
    }
    if (event.target.id === 'equipment-free') {
        equipmentFilter.onlyFree = event.target.checked;
        filterEquipment();
    }
});

document.addEventListener('htmx:afterSwap', (event) => {
    if (event.target.id === 'availability-results-container') filterEquipment();
});

document.addEventListener('click', (event) => {
    const form = document.getElementById('assetFilterForm');
    if (!form) return;
    const tab = event.target.closest('[data-set-status]');
    const chip = event.target.closest('[data-clear]');
    const all = event.target.closest('[data-clear-all]');
    if (!tab && !chip && !all) return;
    event.preventDefault();
    if (tab) form.elements.status.value = tab.dataset.setStatus;
    if (chip) form.elements[chip.dataset.clear].value = '';
    if (all) ['q', 'status', 'department', 'category', 'condition', 'location'].forEach((name) => {
        if (form.elements[name]) form.elements[name].value = '';
    });
    htmx.trigger(form, 'submit');
});
