"""Índice de todo lo exportado: CSV (para Excel) e informe HTML que se puede ordenar."""

import csv
import html
import json
import os

from .planner import human_size

COLUMNS = ["seccion", "ruta_local", "ruta_drive", "estado", "nota", "tipo", "creado",
           "modificado", "tamano", "propietario", "id", "enlace"]


def rows_for(entries, results):
    rows = []
    for e in entries:
        status, note = results.get(id(e), ("", ""))
        item = e.item
        owners = item.get("owners") or []
        rows.append({
            "seccion": e.section.split("/")[0],
            "ruta_local": e.local or (e.dup_of if e.kind == "dup" else ""),
            "ruta_drive": e.drive_path,
            "estado": status,
            "nota": note or e.note,
            "tipo": (e.ext or e.mime.split("/")[-1].replace("vnd.google-apps.", "google ")),
            "creado": (item.get("createdTime") or "")[:19].replace("T", " "),
            "modificado": (item.get("modifiedTime") or "")[:19].replace("T", " "),
            "tamano": e.size or "",
            "propietario": owners[0].get("emailAddress", owners[0].get("displayName", "")) if owners else "",
            "id": e.file_id,
            "enlace": item.get("webViewLink", ""),
        })
    return rows


def write_csv(path, rows):
    # utf-8-sig y ';' para que Excel en español lo abra bien con doble clic
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=";")
        w.writeheader()
        w.writerows(rows)


def write_html(path, rows, title, summary):
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    cards = "".join(
        f"<div class='card'><b>{html.escape(sec)}</b>"
        f"<span>{s['descargas']} archivos · {s['exportaciones']} exportados de Google · "
        f"{s['carpetas']} carpetas</span>"
        f"<span>{human_size(s['bytes'])} en archivos normales"
        f"{' · ' + str(s['omitidos']) + ' omitidos' if s['omitidos'] else ''}"
        f"{' · ' + str(s['duplicados']) + ' repetidos' if s['duplicados'] else ''}</span></div>"
        for sec, s in summary.items()
    )
    page = TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__CARDS__", cards) \
                   .replace("__DATA__", data)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def write_reports(out_dir, entries, results, summary, title):
    os.makedirs(out_dir, exist_ok=True)
    rows = rows_for(entries, results)
    csv_path = os.path.join(out_dir, "_indice.csv")
    html_path = os.path.join(out_dir, "_informe.html")
    write_csv(csv_path, rows)
    write_html(html_path, rows, title, summary)
    return csv_path, html_path


TEMPLATE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Exportación de Drive</title>
<style>
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e4e1da;--acc:#1a5fb4;--err:#b42318;--ok:#2b7a3d}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe7;--mut:#a3a19b;--line:#2e2d2a;--acc:#78aeed;--err:#f97066;--ok:#73c48a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;padding:24px 16px}
h1{font-size:20px;margin:0 0 4px}p{color:var(--mut);margin:0 0 16px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.card{border:1px solid var(--line);border-radius:8px;padding:10px 12px;display:flex;flex-direction:column;gap:2px;min-width:220px}
.card span{color:var(--mut);font-size:13px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
input,select{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:transparent;color:inherit}
input{flex:1;min-width:200px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{cursor:pointer;user-select:none;position:sticky;top:0;background:var(--bg)}
td.path{white-space:normal;word-break:break-word;min-width:260px}
.error{color:var(--err)}.descargado{color:var(--ok)}
a{color:var(--acc)}
</style></head><body>
<h1>__TITLE__</h1>
<p>Índice de lo exportado. Pulsa en una columna para ordenar (por ejemplo, por fecha de modificación).</p>
<div class="cards">__CARDS__</div>
<div class="bar">
<input id="q" placeholder="Buscar por nombre o ruta…">
<select id="sec"><option value="">Todas las secciones</option></select>
<select id="st"><option value="">Todos los estados</option></select>
</div>
<div class="wrap"><table><thead><tr>
<th data-k="ruta_local">Archivo</th><th data-k="estado">Estado</th><th data-k="modificado">Modificado</th>
<th data-k="creado">Creado</th><th data-k="tamano">Tamaño</th><th data-k="propietario">Propietario</th><th>Drive</th>
</tr></thead><tbody id="tb"></tbody></table></div>
<p id="count" style="margin-top:8px"></p>
<script>
const rows=__DATA__;let key="modificado",dir=-1;
const $=s=>document.querySelector(s);
const fill=(sel,vals)=>[...new Set(vals)].filter(Boolean).sort().forEach(v=>{const o=document.createElement("option");o.textContent=v;sel.appendChild(o)});
fill($("#sec"),rows.map(r=>r.seccion));fill($("#st"),rows.map(r=>r.estado));
const size=n=>{n=+n;if(!n)return"";const u=["B","KB","MB","GB"];let i=0;while(n>=1024&&i<3){n/=1024;i++}return n.toFixed(i?1:0)+" "+u[i]};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function draw(){const q=$("#q").value.toLowerCase(),s=$("#sec").value,st=$("#st").value;
let r=rows.filter(x=>(!s||x.seccion==s)&&(!st||x.estado==st)&&(!q||(x.ruta_local+" "+x.ruta_drive).toLowerCase().includes(q)));
r.sort((a,b)=>{let x=a[key],y=b[key];if(key=="tamano"){x=+x||0;y=+y||0}return(x>y?1:x<y?-1:0)*dir});
$("#tb").innerHTML=r.slice(0,5000).map(x=>`<tr><td class="path" title="${esc(x.ruta_drive)}">${esc(x.ruta_local||x.ruta_drive)}${x.nota?`<br><small>${esc(x.nota)}</small>`:""}</td><td class="${esc(x.estado)}">${esc(x.estado)}</td><td>${esc(x.modificado)}</td><td>${esc(x.creado)}</td><td>${size(x.tamano)}</td><td>${esc(x.propietario)}</td><td>${x.enlace?`<a href="${esc(x.enlace)}" target="_blank" rel="noopener">abrir</a>`:""}</td></tr>`).join("");
$("#count").textContent=r.length+" de "+rows.length+" elementos"+(r.length>5000?" (se muestran 5000)":"")}
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{const k=th.dataset.k;dir=key==k?-dir:-1;key=k;draw()});
["#q","#sec","#st"].forEach(s=>$(s).addEventListener("input",draw));draw();
</script></body></html>
"""
