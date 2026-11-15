# Publishing this extension to the IngeTrazo catalog

*[Português abaixo](#português).*

This extension is listed in the community catalog at
<https://ingetrazo.com/extensiones>, whose entries live in
<https://github.com/ingelibre/ingetrazo-extensions> (`extensions/<id>.toml`).

The catalog **holds no code**: each entry names the author's file by URL **and**
its SHA-256, so what a maintainer reviewed is exactly what users download.

## 1. The installable package

IngeTrazo installs one of:

- a single `.py` file, or
- a **`.zip` holding exactly one folder with an `__init__.py` inside** (a Python
  package).

This extension is multi-file, so it ships as a **package ZIP**. The folder is
`igz_calculator/`:

```
igz_calculator/
├── __init__.py          # defines setup(app) — the entry point IngeTrazo loads
├── igz_calculator.py     # the whole extension
├── i18n/                 # en, pt-BR, es, it, fr, de, zh (JSON)
└── icons/                # calculator*.svg, calculator_panel*.svg
```

`__init__.py` **defines** a top-level `setup(app)` (a thin wrapper over the
implementation) because both IngeTrazo and the catalog checker look for a
`setup` function or a `Tool` subclass **in the package's `__init__.py`**.

## 2. Build the ZIP and compute the hash

```python
# from the repository root
import hashlib, os, zipfile

PKG = "igz_calculator"
ZIP = os.path.join("dist", "igz_calculator.zip")
STAMP = (2026, 11, 14, 0, 0, 0)  # fixed mtime -> reproducible ZIP

os.makedirs("dist", exist_ok=True)
if os.path.exists(ZIP):
    os.remove(ZIP)

entries = []
for base, dirs, files in os.walk(PKG):
    dirs[:] = sorted(d for d in dirs if d != "__pycache__")
    for name in sorted(files):
        if name.endswith(".pyc"):
            continue
        full = os.path.join(base, name)
        rel = os.path.relpath(full, PKG).replace("\\", "/")
        entries.append((full, rel))
entries.sort(key=lambda item: item[1])

with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for full, rel in entries:
        info = zipfile.ZipInfo("igz_calculator/" + rel, date_time=STAMP)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        with open(full, "rb") as fh:
            z.writestr(info, fh.read())

digest = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()
with open(ZIP + ".sha256", "w", encoding="ascii", newline="\n") as fh:
    fh.write(digest + "  igz_calculator.zip\n")
print(digest)
```

This produces two files in `dist/` (both git‑ignored, both uploaded to the
release):

- `igz_calculator.zip` — the installable package;
- `igz_calculator.zip.sha256` — `sha256sum` format (`<hash>  <file>`), the same
  value that goes into the catalog TOML.

On Windows you may also verify with:

```powershell
certutil -hashfile dist\igz_calculator.zip SHA256
Get-Content dist\igz_calculator.zip.sha256
```

## 3. Publish and tag

1. Push the source to <https://github.com/em-rezende/Ingetrazo-igz-calculator>.
2. Create a release with a **tag** (e.g. `v1.2.1`), attaching
   `dist/igz_calculator.zip` and `dist/igz_calculator.zip.sha256`.
3. Point `download` at that exact asset, e.g.
   `https://github.com/em-rezende/Ingetrazo-igz-calculator/releases/download/v1.2.1/igz_calculator.zip`.
   Never point `download` at `main`/`master` — the catalog rejects branch URLs.

## 4. Open the pull request

Copy the prepared entry to
`ingetrazo-extensions/extensions/igz_calculator.toml`, add the screenshot to
`ingetrazo-extensions/screenshots/`, and open a pull request. A robot checks the
entry within a minute (complete fields, free licence, matching SHA-256, and a
`setup(app)`/`Tool`); it reads the code and never runs it.

The entry prepared in this repository is
[`ingetrazo-extensions-submission/igz_calculator.toml`](ingetrazo-extensions-submission/igz_calculator.toml).

> The calculator evaluates expressions with a **sandboxed** `eval` (empty
> built-ins, whitelisted `math`/`random`); the checker reports that `eval` for a
> reviewer to read.

---

# Publicação no catálogo do IngeTrazo

Esta extensão é listada no catálogo comunitário em
<https://ingetrazo.com/extensiones>, cujas fichas ficam em
<https://github.com/ingelibre/ingetrazo-extensions> (`extensions/<id>.toml`).
O catálogo **não guarda código**: cada ficha informa a URL do arquivo do autor
**e** seu SHA-256, então o que o mantenedor revisou é exatamente o que os
usuários baixam.

## 1. O pacote instalável

O IngeTrazo instala um `.py` único **ou** um `.zip` contendo **exatamente uma
pasta com `__init__.py`** (um pacote Python). Como esta extensão tem vários
arquivos, ela é distribuída como **ZIP de pacote**: `igz_calculator/`.

O `__init__.py` **define** um `setup(app)` de topo (fina camada sobre a
implementação), pois tanto o IngeTrazo quanto o robô do catálogo procuram uma
função `setup` ou uma subclasse de `Tool` **no `__init__.py` do pacote**.

## 2. Gerar o ZIP e calcular o hash

Use o script da seção em inglês. Ele grava `dist/igz_calculator.zip` e
`dist/igz_calculator.zip.sha256`, ou no Windows confira com:

```powershell
certutil -hashfile dist\igz_calculator.zip SHA256
Get-Content dist\igz_calculator.zip.sha256
```

## 3. Publicar e etiquetar

1. Envie o código para <https://github.com/em-rezende/Ingetrazo-igz-calculator>.
2. Crie uma *release* com uma **tag** (ex.: `v1.2.1`) e anexe
   `dist/igz_calculator.zip` e `dist/igz_calculator.zip.sha256` como assets.
3. Aponte `download` para esse asset exato. **Nunca** aponte `download` para
   `main`/`master` — o catálogo rejeita URLs de branch.

## 4. Abrir o pull request

Copie a ficha preparada para `ingetrazo-extensions/extensions/igz_calculator.toml`,
adicione o screenshot em `ingetrazo-extensions/screenshots/` e abra o pull
request. Um robô verifica a ficha em ~1 minuto (campos completos, licença livre,
SHA-256 correspondente e `setup(app)`/`Tool`); ele lê o código e nunca o executa.

## Licença

GPL-3.0-or-later — a mesma do IngeTrazo.
