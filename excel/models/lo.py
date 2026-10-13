"""LibreOffice (headless) for format conversion and full recalculation.

A private profile sets 'always recalculate on load' for Excel and ODF files, so converting a
workbook to .xlsx recalculates every formula and stores the results; reading those cached
results back is how models are verified.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

XCU = '''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Filter/Import/VBA"><prop oor:name="Load" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Filter/Import/VBA"><prop oor:name="Save" oor:op="fuse"><value>true</value></prop></item>
</oor:items>
'''
FILTERS = {'xlsx': 'xlsx:Calc MS Excel 2007 XML', 'xlsm': 'xlsm:Calc MS Excel 2007 VBA XML'}


def soffice():
    for name in ('soffice', 'libreoffice', r'C:\Program Files\LibreOffice\program\soffice.exe'):
        p = shutil.which(name) or (name if os.path.exists(name) else None)
        if p:
            return p
    raise RuntimeError('LibreOffice (soffice) not found')


_PROFILE = None


def _profile():
    global _PROFILE
    if _PROFILE is None:
        d = Path(tempfile.mkdtemp(prefix='lo_profile_'))
        (d / 'user').mkdir(parents=True)
        (d / 'user' / 'registrymodifications.xcu').write_text(XCU, encoding='utf-8')
        _PROFILE = d.as_uri()
    return _PROFILE


def convert(paths, outdir, fmt='xlsx', timeout=600):
    """Converts (and recalculates) files into outdir. Returns {input path: output path or None}."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = [Path(p) for p in paths]
    if not paths:
        return {}
    cmd = [soffice(), f'-env:UserInstallation={_profile()}', '--headless', '--norestore', '--nolockcheck',
           '--convert-to', FILTERS[fmt], '--outdir', str(outdir)] + [str(p) for p in paths]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        subprocess.run(['pkill', '-9', '-f', 'soffice'], check=False)
    out = {}
    for p in paths:
        q = outdir / (p.stem + '.' + fmt)
        out[str(p)] = str(q) if q.exists() and q.stat().st_size > 0 else None
    return out


def recalculated_errors(xlsx_path):
    """Reads a LibreOffice-recalculated workbook: ({error text: count}, formula cell count, {sheet!cell: value})."""
    from .xlsxml import Package, col_letters
    pkg = Package(xlsx_path)
    errors, formulas, values = {}, 0, {}
    for name, part in pkg.sheets:
        for (r, c), (kind, val, formula) in pkg.grid(part).items():
            if formula is not None:
                formulas += 1
            if kind == 'e' and val:
                errors[val] = errors.get(val, 0) + 1
            elif name in ('Checks',) and val is not None:
                values[f'{name}!{col_letters(c)}{r}'] = val
    return errors, formulas, values
