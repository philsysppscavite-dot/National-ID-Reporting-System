{% extends "base.html" %}

{% block content %}
<section class="page-head">
  <div>
    <p class="eyebrow">Schedule</p>
    <h2>{{ "Edit Schedule" if schedule else "Add Schedule" }}</h2>
  </div>
  <a class="button-link secondary" href="{{ url_for('schedules') }}">Back</a>
</section>

<section class="panel form-panel">
  <form method="post" class="grid-form">
    <label>Date
      <input type="date" name="schedule_date" value="{{ schedule['schedule_date'] if schedule else '' }}" required>
    </label>

    <label>City / Municipality
      {% set selected_city = schedule['city_municipality'] if schedule else '' %}
      <select name="city_municipality" required>
        <option value="">Select city / municipality</option>
        {% for city in city_municipalities %}
        <option value="{{ city }}" {% if selected_city == city %}selected{% endif %}>{{ city }}</option>
        {% endfor %}
        {% if selected_city and selected_city not in city_municipalities %}
        <option value="{{ selected_city }}" selected>{{ selected_city }}</option>
        {% endif %}
      </select>
    </label>

    <label>Assigned Registration Kit Operator
      {% set selected_rko_ids = schedule['assigned_rko_employee_ids'] if schedule else [] %}
      <select name="assigned_rko_employee_ids" multiple size="6">
        {% for employee in rko_employees %}
        <option value="{{ employee['id'] }}" {% if employee['id'] in selected_rko_ids %}selected{% endif %}>
          {{ employee["full_name"] }}
        </option>
        {% endfor %}
      </select>
    </label>

    <label>Assigned Registration Assistant
      {% set selected_ra_ids = schedule['assigned_ra_employee_ids'] if schedule else [] %}
      <select name="assigned_ra_employee_ids" multiple size="6">
        {% for employee in ra_employees %}
        <option value="{{ employee['id'] }}" {% if employee['id'] in selected_ra_ids %}selected{% endif %}>
          {{ employee["full_name"] }}
        </option>
        {% endfor %}
      </select>
    </label>

    <div class="full-row schedule-counts">
      <div class="count-card">
        <strong>Registration Kit Operator</strong>
        <div>Total: <span id="rko-total">{{ rko_total }}</span></div>
        <div>Needed: <input type="number" id="rko-needed-input" name="needed_rko_count" min="0" value="{{ schedule['needed_rko_count'] if schedule else 1 }}"></div>
        <div>Selected: <span id="rko-selected">0</span></div>
        <div>Remaining: <span id="rko-remaining">0</span></div>
      </div>
      <div class="count-card">
        <strong>Registration Assistant</strong>
        <div>Total: <span id="ra-total">{{ ra_total }}</span></div>
        <div>Needed: <input type="number" id="ra-needed-input" name="needed_ra_count" min="0" value="{{ schedule['needed_ra_count'] if schedule else 1 }}"></div>
        <div>Selected: <span id="ra-selected">0</span></div>
        <div>Remaining: <span id="ra-remaining">0</span></div>
      </div>
    </div>

    <label class="full-row">Event / Place / Activity
      <textarea name="event_place_activity" rows="3">{{ schedule['event_place_activity'] if schedule else '' }}</textarea>
    </label>

    <label>Status
      {% set selected_status = schedule['status'] if schedule else 'Pending' %}
      <select name="status" required>
        <option value="Pending" {% if selected_status == 'Pending' %}selected{% endif %}>Pending</option>
        <option value="Approved" {% if selected_status == 'Approved' %}selected{% endif %}>Approved</option>
      </select>
    </label>

    <label>Vehicle
      {% set selected_vehicle = schedule['vehicle'] if schedule else 'PSA' %}
      <select name="vehicle" required>
        <option value="PSA" {% if selected_vehicle == 'PSA' %}selected{% endif %}>PSA</option>
        <option value="LGU" {% if selected_vehicle == 'LGU' %}selected{% endif %}>LGU</option>
        <option value="Agency" {% if selected_vehicle == 'Agency' %}selected{% endif %}>Agency</option>
      </select>
    </label>

    <div class="full-row">
      <button type="submit">Save Schedule</button>
    </div>
  </form>
</section>

<script>
  (function () {
    const assignedByDate = {{ assigned_by_date|tojson }};
    const dateInput = document.querySelector("input[name='schedule_date']");
    const rkoSelect = document.querySelector("select[name='assigned_rko_employee_ids']");
    const raSelect = document.querySelector("select[name='assigned_ra_employee_ids']");
    const rkoNeededInput = document.getElementById("rko-needed-input");
    const raNeededInput = document.getElementById("ra-needed-input");
    if (!dateInput || !rkoSelect || !raSelect || !rkoNeededInput || !raNeededInput) return;

    function setCounts() {
      const rkoSelected = Array.from(rkoSelect.selectedOptions).filter((o) => o.value).length;
      const raSelected = Array.from(raSelect.selectedOptions).filter((o) => o.value).length;
      const rkoNeeded = Math.max(0, parseInt(rkoNeededInput.value || "0", 10));
      const raNeeded = Math.max(0, parseInt(raNeededInput.value || "0", 10));
      document.getElementById("rko-selected").textContent = String(rkoSelected);
      document.getElementById("ra-selected").textContent = String(raSelected);
      document.getElementById("rko-remaining").textContent = String(Math.max(0, rkoNeeded - rkoSelected));
      document.getElementById("ra-remaining").textContent = String(Math.max(0, raNeeded - raSelected));
    }

    function disableAssignedOptions() {
      const key = (dateInput.value || "").trim();
      const used = assignedByDate[key] || { rko_ids: [], ra_ids: [] };
      const usedRko = new Set((used.rko_ids || []).map(String));
      const usedRa = new Set((used.ra_ids || []).map(String));

      for (const option of rkoSelect.options) {
        if (!option.value) continue;
        option.disabled = usedRko.has(option.value) && !option.selected;
      }
      for (const option of raSelect.options) {
        if (!option.value) continue;
        option.disabled = usedRa.has(option.value) && !option.selected;
      }
      setCounts();
    }

    dateInput.addEventListener("change", disableAssignedOptions);
    rkoSelect.addEventListener("change", disableAssignedOptions);
    raSelect.addEventListener("change", disableAssignedOptions);
    rkoNeededInput.addEventListener("input", setCounts);
    raNeededInput.addEventListener("input", setCounts);
    disableAssignedOptions();
  })();
</script>
{% endblock %}
