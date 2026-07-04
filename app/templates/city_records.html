{% extends "base.html" %}

{% block content %}
<section class="page-head">
  <div>
    <p class="eyebrow">City / Municipality Summary</p>
    <h2>Service Summary by Sex and Total</h2>
  </div>
  <div class="actions">
    <a class="button-link secondary" target="_blank" href="{{ url_for('city_records_report', start_date=start_date, end_date=end_date) }}">Print PDF</a>
  </div>
</section>

<section class="panel">
  <form method="get" class="filters">
    <input type="date" name="start_date" value="{{ start_date }}">
    <input type="date" name="end_date" value="{{ end_date }}">
    <button type="submit">Load Record</button>
  </form>

  <table>
    <thead>
      <tr>
        <th rowspan="2">City / Municipality</th>
        {% for service in service_types %}
        <th colspan="3">{{ service }}</th>
        {% endfor %}
        <th colspan="3">Grand Total</th>
      </tr>
      <tr>
        {% for service in service_types %}
        <th>Male</th>
        <th>Female</th>
        <th>Total</th>
        {% endfor %}
        <th>Male</th>
        <th>Female</th>
        <th>Total</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td>{{ row["city_municipality"] }}</td>
        {% for service in service_types %}
        <td>{{ row["services"][service]["male"] }}</td>
        <td>{{ row["services"][service]["female"] }}</td>
        <td>{{ row["services"][service]["total"] }}</td>
        {% endfor %}
        <td>{{ row["male"] }}</td>
        <td>{{ row["female"] }}</td>
        <td>{{ row["total"] }}</td>
      </tr>
      {% else %}
      <tr><td colspan="{{ 1 + (service_types|length * 3) + 3 }}">No records found for the selected date range.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
