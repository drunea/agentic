function esc(value) {
  var div = document.createElement("div");
  div.textContent = value === null || value === undefined ? "" : String(value);
  return div.innerHTML;
}

function renderStatementTable(root, args) {
  var columns = args.columns || [];
  var rows = args.rows || [];
  var maxHeight = args.max_height || 600;

  var headerHtml = "<th></th>";
  columns.forEach(function (col) {
    var cls = col.is_estimate ? ' class="fs-estimate"' : "";
    headerHtml += "<th" + cls + ">" + esc(col.label) +
      '<span class="fs-date">' + esc(col.date) + "</span></th>";
  });

  var bodyHtml = "";
  rows.forEach(function (row) {
    var classes = [];
    if (row.is_bold) classes.push("fs-bold");
    if (row.is_subheader) classes.push("fs-subheader");
    var clsAttr = classes.length ? ' class="' + classes.join(" ") + '"' : "";
    var indentStyle = row.indent ? ' style="padding-left:' + (10 + row.indent * 16) + 'px"' : "";
    var titleAttr = row.tooltip ? ' title="' + esc(row.tooltip) + '"' : "";
    var rowHtml = "<td" + indentStyle + titleAttr + ">" + esc(row.label) + "</td>";
    (row.values || []).forEach(function (v, i) {
      var estCls = columns[i] && columns[i].is_estimate ? ' class="fs-estimate"' : "";
      rowHtml += "<td" + estCls + ">" + esc(v) + "</td>";
    });
    bodyHtml += "<tr" + clsAttr + ">" + rowHtml + "</tr>";
  });

  root.innerHTML = '<div class="fs-table-wrap" style="max-height:' + maxHeight + 'px">' +
    '<table class="fs-table"><thead><tr>' + headerHtml + "</tr></thead><tbody>" +
    bodyHtml + "</tbody></table></div>";
}

function renderSimpleTable(root, args) {
  var columns = args.columns || [];
  var rows = args.rows || [];

  var headerHtml = "<th></th>";
  columns.forEach(function (c) { headerHtml += "<th>" + esc(c) + "</th>"; });

  var bodyHtml = "";
  rows.forEach(function (row) {
    var clsAttr = row.is_bold ? ' class="fs-bold"' : "";
    var titleAttr = row.tooltip ? ' title="' + esc(row.tooltip) + '"' : "";
    var rowHtml = "<td" + titleAttr + ">" + esc(row.label) + "</td>";
    (row.values || []).forEach(function (v) { rowHtml += "<td>" + esc(v) + "</td>"; });
    bodyHtml += "<tr" + clsAttr + ">" + rowHtml + "</tr>";
  });

  root.innerHTML = '<div class="fs-table-wrap" style="max-height:none;overflow:visible">' +
    '<table class="fs-table"><thead><tr>' + headerHtml + "</tr></thead><tbody>" +
    bodyHtml + "</tbody></table></div>";
}

export default function (component) {
  var data = component.data || {};
  var root = component.parentElement.querySelector("#fs-root");
  if (data.mode === "simple") {
    renderSimpleTable(root, data);
  } else {
    renderStatementTable(root, data);
  }
}
