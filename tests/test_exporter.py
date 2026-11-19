import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drive_exporter import formats
from drive_exporter.exporter import Exporter
from drive_exporter.names import NameRegistry, sanitize, with_extension
from drive_exporter.planner import Options, Planner, summarize
from drive_exporter.report import write_reports
from tests.fake_drive import scenario

quiet = lambda *_: None


def plan(drive, **kw):
    return Planner(drive, Options(**kw), log=quiet).build()


def by_local(entries):
    return {e.local: e for e in entries if e.local}


def run(drive, out, **kw):
    entries = plan(drive, **kw)
    results = Exporter(drive, str(out), log=quiet, threads=kw.pop("threads", 2)).run(entries)
    return entries, {e.local or e.drive_path: results[id(e)][0] for e in entries}


# ---------- nombres ----------
def test_sanitize_and_reserved_names():
    assert sanitize('a:b/c?') == "a_b_c_"
    assert sanitize("CON.txt") == "CON_.txt"
    assert sanitize("  punto final. ") == "punto final"
    assert len(sanitize("x" * 400 + ".pdf")) <= 150 and sanitize("x" * 400 + ".pdf").endswith(".pdf")
    assert with_extension("Informe.docx", "docx") == "Informe.docx"
    assert with_extension("Informe", "html.zip") == "Informe.html.zip"


def test_name_registry_is_case_insensitive():
    r = NameRegistry()
    assert r.reserve("d", "foto.jpg") == "foto.jpg"
    assert r.reserve("d", "FOTO.jpg") == "FOTO (2).jpg"
    assert r.reserve("e", "foto.jpg") == "foto.jpg"


def test_format_args():
    f = formats.parse_format_args({"doc": "docx,pdf"})
    assert f["doc"] == ["docx", "pdf"] and f["sheet"] == ["xlsx"]
    try:
        formats.parse_format_args({"sheet": "docx"})
        assert False
    except ValueError:
        pass


# ---------- plan ----------
def test_plan_sections_and_paths():
    entries = plan(scenario())
    local = by_local(entries)
    # Mi unidad
    assert "Mi unidad/Universidad/Informe.docx" in local            # el binario (más antiguo)
    assert local["Mi unidad/Universidad/Informe.docx"].kind in ("download", "export")
    assert "Mi unidad/Universidad/Informe (2).docx" in local         # el otro no se machaca
    assert "Mi unidad/Universidad/foto.jpg" in local
    assert "Mi unidad/Universidad/FOTO (2).jpg" in local
    assert "Mi unidad/Universidad/Tema_ 1_2_/Notas.xlsx" in local
    # El acceso directo se convierte en la carpeta real, con el nombre del acceso
    assert "Mi unidad/Atajo a Ana/apuntes.pdf" in local
    # La carpeta compartida no se baja dos veces: en Compartido conmigo queda como repetida
    dups = [e for e in entries if e.kind == "dup"]
    assert any(e.file_id == "S" and e.section == "Compartido conmigo" for e in dups)
    assert "Compartido conmigo/suelto.txt" in local
    assert "Mi unidad (sin carpeta)/perdido.txt" in local
    assert "Unidades compartidas/Equipo/plan.txt" in local
    skips = {e.name: e.note for e in entries if e.kind == "skip"}
    assert "formularios" in skips["Encuesta"]
    assert "roto" in skips["Roto"].lower()
    assert "desactivado" in skips["Protegido.pdf"]


def test_plan_only_shared_with_me():
    entries = plan(scenario(), sources=("compartido",))
    assert entries and all(e.section == "Compartido conmigo" for e in entries)
    # Sin Mi unidad, el acceso directo de Mi unidad no se sigue, y la carpeta de Ana
    # se baja en Compartido conmigo
    assert "Compartido conmigo/Carpeta de Ana/apuntes.pdf" in by_local(entries)


def test_multiple_formats_and_only_google():
    entries = plan(scenario(), formats=formats.parse_format_args({"doc": "docx,pdf"}))
    local = by_local(entries)
    assert "Mi unidad/Universidad/Informe.pdf" in local
    entries = plan(scenario(), only_google=True)
    assert not any(e.kind == "download" for e in entries)


def test_date_layout():
    local = by_local(plan(scenario(), layout="fecha"))
    assert "Mi unidad/2020/2020-05/foto.jpg" in local
    assert not any(e.kind == "folder" for e in plan(scenario(), layout="fecha"))


def test_ignore_shortcuts():
    entries = plan(scenario(), shortcuts="ignorar")
    assert "Compartido conmigo/Carpeta de Ana/apuntes.pdf" in by_local(entries)


# ---------- ejecución ----------
def test_full_run_writes_files_with_dates(tmp_path):
    d = scenario()
    entries, st = run(d, tmp_path)
    p = tmp_path / "Mi unidad" / "Universidad" / "foto.jpg"
    assert p.read_bytes() == b"jpeg1"
    expected = datetime.fromisoformat("2020-05-05T05:05:05+00:00").timestamp()
    assert abs(p.stat().st_mtime - expected) < 2
    assert (tmp_path / "Unidades compartidas" / "Equipo" / "plan.txt").read_bytes() == b"plan"
    assert (tmp_path / "Mi unidad" / "Atajo a Ana" / "apuntes.pdf").exists()
    # carpeta con la fecha de Drive
    folder = tmp_path / "Mi unidad" / "Universidad"
    assert abs(folder.stat().st_mtime - datetime.fromisoformat("2023-06-30T10:00:00+00:00").timestamp()) < 2
    assert st["Mi unidad/Universidad/foto.jpg"] == "descargado"
    assert not list(tmp_path.rglob("*.part"))


def test_rerun_skips_unchanged_and_handles_changes(tmp_path):
    d = scenario()
    run(d, tmp_path)
    d.calls.clear()
    _, st = run(d, tmp_path)
    assert not any(c[0] in ("download", "export") for c in d.calls)
    assert set(v for k, v in st.items() if v not in ("omitido", "duplicado", "carpeta")) == {"sin cambios"}

    # Cambia un archivo en Drive y otro se renombra
    d.touch("img1", "2024-01-01T00:00:00.000Z", b"jpeg1-v2")
    d.files["d1"]["name"] = "plan definitivo.txt"
    d.calls.clear()
    _, st = run(d, tmp_path)
    assert st["Mi unidad/Universidad/foto.jpg"] == "descargado"
    assert (tmp_path / "Mi unidad" / "Universidad" / "foto.jpg").read_bytes() == b"jpeg1-v2"
    assert st["Unidades compartidas/Equipo/plan definitivo.txt"] == "movido"
    assert not (tmp_path / "Unidades compartidas" / "Equipo" / "plan.txt").exists()
    assert ("download", "d1") not in d.calls


def test_md5_mismatch_is_an_error_and_retried_next_time(tmp_path):
    d = scenario()
    d.corrupt.add("T")
    _, st = run(d, tmp_path)
    assert st["Compartido conmigo/suelto.txt"] == "error"
    assert not (tmp_path / "Compartido conmigo" / "suelto.txt").exists()
    d.corrupt.clear()
    _, st = run(d, tmp_path)
    assert st["Compartido conmigo/suelto.txt"] == "descargado"


def test_big_export_uses_export_link(tmp_path):
    d = scenario()
    d.export_limit.add("doc1")
    _, st = run(d, tmp_path)
    assert ("export_link", "doc1") in d.calls
    assert st["Mi unidad/Universidad/Informe (2).docx"] == "descargado"


def _export(d, tmp_path):
    entries = plan(d)
    results = Exporter(d, str(tmp_path), log=quiet).run(entries)
    return entries, results


def test_trash_plan_only_mine_and_complete_folders(tmp_path):
    from drive_exporter.cleanup import plan_trash
    d = scenario()
    entries, results = _export(d, tmp_path)
    tp = plan_trash(entries, results)
    files = {f[0] for f in tp.files}
    folders = {f[0] for f in tp.folders}
    # mío y bien descargado
    assert {"doc1", "bin1", "img1", "img2", "sh1", "O"} <= files
    # de otras personas, de una unidad compartida o sin descargar: se quedan
    assert not files & {"s1", "T", "d1", "nodl", "form1"}
    # "Tema" solo tiene la hoja (descargada): va entera. "Universidad" tiene un formulario
    # y un PDF protegido que no se han podido bajar: se queda.
    assert "B" in folders and "A" not in folders
    assert "S" not in folders  # carpeta de otra persona
    assert tp.kept["es de otra persona"] >= 2
    assert tp.kept["está en una unidad compartida"] == 1


def test_trash_plan_skips_failed_downloads(tmp_path):
    from drive_exporter.cleanup import plan_trash
    d = scenario()
    d.export_limit.add("sh1")  # falla la exportación (sin enlace alternativo)
    entries, results = _export(d, tmp_path)
    tp = plan_trash(entries, results)
    assert "sh1" not in {f[0] for f in tp.files}
    assert "B" not in {f[0] for f in tp.folders}, "la carpeta no puede irse si algo de dentro falló"


def test_run_trash_rechecks_changes(tmp_path):
    from drive_exporter.cleanup import plan_trash, run_trash
    d = scenario()
    entries, results = _export(d, tmp_path)
    tp = plan_trash(entries, results)
    d.touch("sh1", "2030-01-01T00:00:00.000Z")   # alguien lo edita después de descargarlo
    sent, skipped = run_trash(d, tp, log=quiet)
    assert "sh1" not in d.trashed and "B" not in d.trashed
    assert "doc1" in d.trashed and "O" in d.trashed
    assert skipped == 1
    assert not set(d.trashed) & {"s1", "T", "d1", "S", "A"}


def test_dry_run_trash_preview_touches_nothing(tmp_path):
    from drive_exporter.cleanup import plan_trash
    d = scenario()
    entries = plan(d)
    results = Exporter(d, str(tmp_path), log=quiet).run(entries, dry_run=True)
    tp = plan_trash(entries, results, assume_ok=True)
    assert tp.files and d.trashed == []


def test_dry_run_downloads_nothing_and_reports(tmp_path):
    d = scenario()
    entries = plan(d)
    results = Exporter(d, str(tmp_path), log=quiet).run(entries, dry_run=True)
    assert not any(c[0] in ("download", "export") for c in d.calls)
    csv_path, html_path = write_reports(str(tmp_path), entries, results, summarize(entries), "t")
    with open(csv_path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert any(r["estado"] == "simulado" for r in rows)
    assert "Mi unidad" in open(html_path, encoding="utf-8").read()


def test_single_folder(tmp_path):
    d = scenario()
    entries = Planner(d, Options(folder_id="B"), log=quiet).build()
    assert [e.local for e in entries] == ["Tema_ 1_2_/Notas.xlsx"]


def test_cli_end_to_end(tmp_path, monkeypatch):
    import json
    import drive_exporter.api as api
    from drive_exporter import cli
    d = scenario()
    monkeypatch.setattr(api, "authenticate", lambda *a, **k: object())
    monkeypatch.setattr(api, "DriveClient", lambda creds, log=None: d)
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"installed": {"client_id": "x"}}))
    out = tmp_path / "salida"
    base = ["--credenciales", str(creds)]
    code = cli.main(base + ["-o", str(out), "--si", "--doc", "docx,pdf", "--hilos", "3"])
    assert code == 0
    assert (out / "Mi unidad" / "Universidad" / "Informe.pdf").exists()
    assert (out / "_informe.html").exists() and (out / "_indice.csv").exists()
    assert (out / ".drive-exporter" / "registro.log").exists()
    assert d.trashed == [], "sin --mandar-a-papelera no se toca Drive"
    code = cli.main(base + ["-o", str(out / "sim"), "--simular", "--origen", "compartido", "--mandar-a-papelera"])
    assert code == 0 and not (out / "sim" / "Compartido conmigo").exists() and d.trashed == []
    # de verdad, con --si: solo lo mío y completo
    code = cli.main(base + ["-o", str(out), "--si", "--mandar-a-papelera"])
    assert code == 0
    assert "doc1" in d.trashed and "B" in d.trashed and "T" not in d.trashed


def test_cli_without_credentials_stops_early(tmp_path, monkeypatch):
    from drive_exporter import cli
    monkeypatch.setattr(cli, "CONFIG_FILE", str(tmp_path / "cfg.json"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "HERE", str(tmp_path))
    assert cli.main(["-o", str(tmp_path / "x"), "--si"]) == 2
