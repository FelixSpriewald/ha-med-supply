# Medication Supply (`med_supply`)

Home-Assistant-Integration, die den Tablettenvorrat aus einem festen Einnahmeplan
mitrechnet und rechtzeitig per Push ans neue Rezept erinnert.

Du pflegst nur zwei Dinge:

- **Einnahmeplan** – Dosis in mg zu bis zu vier Zeitpunkten (morgens/mittags/abends/nachts)
- **Zugänge** – „+50 Tbl. à 5 mg", gelegentlich eine Korrektur nach dem Nachzählen

Alles andere rechnet die Integration.

## Wie gerechnet wird

- Vorrat wird intern in **mg** geführt. Dadurch funktionieren Dosis ≠ Tablettenstärke
  (10 mg = 2× 5 mg), Stärkewechsel und gemischte Packungen.
- Gespeichert wird nur ein Stand (mg + Zeitpunkt). Der aktuelle Vorrat = Stand minus alle
  Plan-Einnahmen seitdem — stimmt also auch nach Neustart oder Ausfall.
- Planänderung: Beim Speichern wird der Verbrauch nach altem Plan festgeschrieben, der neue
  gilt ab jetzt.
- **Leer am** = erste Einnahme, die nicht mehr voll gedeckt ist. **Rezept bis** = Leer am − Vorlaufzeit.
- Dosen, die sich nicht mit ganzen/halben Tabletten abbilden lassen, lehnt der Dialog ab.

## Entitäten (pro Medikament ein Gerät)

| Entität | |
|---|---|
| `sensor.*_vorrat` | Tabletten (Attribute: `stock_mg`, `strength_mg`) |
| `sensor.*_reichweite` | Tage bis leer |
| `sensor.*_leer_am`, `sensor.*_rezept_bis` | Datum |
| `sensor.*_status` | `ok` / `due` / `requested` / `empty` |
| `sensor.*_tagesdosis` | mg/Tag, Attribut `plan` („morgens 10 mg (2× 5 mg), …") |
| `sensor.*_nachste_einnahme` | Zeitstempel |
| `number.*_zugang` + `button.*_zugang_buchen` | Zugang eintragen und buchen |
| `number.*_gezahlt` + `button.*_zahlung_ubernehmen` | Korrektur nach Nachzählen |
| `button.*_1_packung` | +1 Packung (nur mit Packungsgröße) |
| `switch.*_rezept_angefragt` | stoppt die Rezept-Erinnerung; wird beim Zugang automatisch aus |

(IDs bei deutscher HA-Sprache; bei Englisch `*_supply`, `*_days_left`, …)

## Erinnerungen

Täglich zur eingestellten Uhrzeit an das gewählte Companion-App-Gerät:

- **Rezept holen** – sobald Reichweite ≤ Vorlaufzeit, bis „Rezept angefragt" gesetzt ist.
  Buttons im Push: *Rezept angefragt*, *In 3 h erinnern*.
- **Packung abholen** – wenn angefragt, aber nur noch ≤ 3 Tage Reichweite.

Ohne die Option „Name im Push zeigen" steht nur „Ein Medikament …" im Text (Sperrbildschirm).

Aktionen: `med_supply.add_stock`, `med_supply.set_stock`, `med_supply.set_requested`,
`med_supply.send_reminder` (sofort senden, zum Testen).

## Installation (HACS)

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/FelixSpriewald/ha-med-supply`, Typ *Integration*.
2. „Medication Supply" installieren, HA neu starten.
3. Einstellungen → Geräte & Dienste → *Integration hinzufügen* → „Medication Supply".

Manuell: `custom_components/med_supply/` nach `/config/custom_components/` kopieren.

## Dashboard

Die Integration bringt eine eigene Karte mit und lädt sie automatisch, eine Ressource muss
nicht eingetragen werden. Im Dashboard: *Karte hinzufügen* → „Medikamentenvorrat" oder

```yaml
type: custom:med-supply-card
```

Ohne Konfiguration zeigt sie alle Medikamente. Optional `title` und `device_id`.
Sie zeigt Reichweite als Balken mit Vorlauf-Markierung, Status, Leer-Datum, den Einnahmeplan
mit Tabletten-Symbolen und Buttons für *+ Packung*, *Zugang…*, *Gezählt…* und *Rezept angefragt*.

Lokale Vorschau mit Beispieldaten: `python3 -m http.server` im Repo, dann
`http://localhost:8000/dev/preview.html`.

## Entwicklung

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```
