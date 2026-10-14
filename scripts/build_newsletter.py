"""Arma el newsletter semanal de Argentina Invest Monitor en cuatro idiomas.

Lee los JSON de data/, escribe cada edición en newsletter/<año-semana>/<idioma>.md
y, si BUTTONDOWN_API_KEY está definida, la sube a Buttondown como borrador
dirigido a los suscriptores con la etiqueta lang-<idioma>.

Variables de entorno:
  BUTTONDOWN_API_KEY   clave de la API de Buttondown (opcional)
  NEWSLETTER_STATUS    "draft" (por defecto) o "send" para enviar sin revisión
  NEWSLETTER_DATE      fecha de la edición, AAAA-MM-DD (por defecto, hoy)
"""

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "newsletter"
SITE = "https://argentinainvestmonitor-gamma.vercel.app"
LANGS = ["es", "en", "pt", "el"]
API = "https://api.buttondown.com/v1"

MONTHS = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "pt": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    "el": ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μαΐ", "Ιουν", "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"],
}

MILLION = {"es": "millones", "en": "million", "pt": "milhões", "el": "εκατ."}
SMALL = {"de", "del", "la", "las", "el", "los", "y", "e", "para", "en"}


def nice_case(s):
    w = s.lower().split()
    return " ".join(x if (i and x in SMALL) else x[:1].upper() + x[1:] for i, x in enumerate(w))


T = {
    "es": {
        "subject": "Argentina Invest Monitor · Semana del {d}",
        "intro": "Los datos públicos que movieron la semana, ordenados para inversores. Todas las cifras salen de fuentes oficiales y se actualizan solas en el portal.",
        "h_vm": "Vaca Muerta",
        "vm_oil": "**Petróleo:** {v} barriles diarios en {p}, {y} interanual.",
        "vm_gas": "**Gas:** {v} millones de m³ diarios, {y} interanual.",
        "vm_share": "**Peso nacional:** {v} del petróleo del país sale de Vaca Muerta.",
        "vm_wells": "**Pozos:** {a} activos; {n} pozos nuevos en los últimos doce meses.",
        "vm_frac": "**Fractura:** {v} etapas en los últimos doce meses, {y} interanual.",
        "vm_price": "**Precio realizado en Neuquén:** USD {v} por barril en {p}.",
        "h_mk": "Mercados y macro",
        "mk_brent": "**Brent:** USD {b} · **WTI:** USD {w} (al {d}).",
        "mk_fx": "**Dólar mayorista:** ${v} por dólar (al {d}), {y} interanual.",
        "mk_res": "**Reservas del BCRA:** USD {v} millones (al {d}), {c} en un año.",
        "mk_cpi": "**Inflación:** {m} mensual y {y} interanual en {p}.",
        "mk_badlar": "**Tasa BADLAR:** {v} anual (hace un año, {y1}).",
        "h_rigi": "RIGI: proyectos aprobados",
        "rigi_line": "**{proj}** · {co} · USD {usd} millones · aprobado el {d}. [Boletín Oficial]({url})",
        "h_bo": "Boletín Oficial: normas de la semana",
        "h_sec": "Otros sectores",
        "sec_min": "**Minería:** exportaciones por USD {v} millones en los últimos doce meses a {p}, {y} interanual.",
        "sec_agro": "**Agro:** liquidación de divisas por USD {v} millones en doce meses a {p}, {y} interanual.",
        "sec_ind": "**Industria:** el índice de producción industrial varió {y} interanual en {p}.",
        "sec_act": "**Actividad:** el EMAE marcó {v} puntos en {p} ({c} contra el mes anterior).",
        "h_news": "En los medios",
        "news_note": "",
        "h_firm": "Asesoramiento legal para invertir en Argentina",
        "firm": "Con raíces en Grecia y en Córdoba, el estudio une una tradición vinculada a los negocios internacionales con el conocimiento del derecho argentino. Tradición y actualidad unidas para sumar valor a nuestros clientes y seguridad jurídica a sus inversiones.\n\nOnassis & Baronetto acompaña a empresas e inversores en RIGI, energía, minería, agro y estructuración de inversiones. Escribinos a [onassisbaronettolawyers@gmail.com](mailto:onassisbaronettolawyers@gmail.com) o conocé el estudio en [el portal]({url}).",
        "more": "Ver el tablero completo",
        "foot": "Fuentes: Secretaría de Energía, BCRA, INDEC, Boletín Oficial, MAGyP, SIACAM, EIA. Información con fines informativos; no constituye asesoramiento financiero.",
    },
    "en": {
        "subject": "Argentina Invest Monitor · Week of {d}",
        "intro": "The public data that moved this week, organized for investors. Every figure comes from official sources and updates automatically on the portal.",
        "h_vm": "Vaca Muerta",
        "vm_oil": "**Oil:** {v} barrels per day in {p}, {y} year on year.",
        "vm_gas": "**Gas:** {v} million m³ per day, {y} year on year.",
        "vm_share": "**National weight:** {v} of Argentina's oil comes from Vaca Muerta.",
        "vm_wells": "**Wells:** {a} active; {n} new wells in the last twelve months.",
        "vm_frac": "**Fracking:** {v} stages in the last twelve months, {y} year on year.",
        "vm_price": "**Realized price in Neuquén:** USD {v} per barrel in {p}.",
        "h_mk": "Markets and macro",
        "mk_brent": "**Brent:** USD {b} · **WTI:** USD {w} (as of {d}).",
        "mk_fx": "**Wholesale dollar:** ARS {v} per USD (as of {d}), {y} year on year.",
        "mk_res": "**Central bank reserves:** USD {v} million (as of {d}), {c} over one year.",
        "mk_cpi": "**Inflation:** {m} month on month and {y} year on year in {p}.",
        "mk_badlar": "**BADLAR rate:** {v} annual (a year ago, {y1}).",
        "h_rigi": "RIGI: approved projects",
        "rigi_line": "**{proj}** · {co} · USD {usd} million · approved {d}. [Official Gazette]({url})",
        "h_bo": "Official Gazette: this week's rules",
        "h_sec": "Other sectors",
        "sec_min": "**Mining:** exports of USD {v} million in the twelve months to {p}, {y} year on year.",
        "sec_agro": "**Agriculture:** export FX settlements of USD {v} million in the twelve months to {p}, {y} year on year.",
        "sec_ind": "**Industry:** industrial production changed {y} year on year in {p}.",
        "sec_act": "**Activity:** the EMAE index stood at {v} in {p} ({c} month on month).",
        "h_news": "In the press",
        "news_note": "Headlines in Spanish, as published by each outlet.",
        "h_firm": "Legal advice for investing in Argentina",
        "firm": "With roots in Greece and in Córdoba, the firm brings together a tradition tied to international business and a deep knowledge of Argentine law. Tradition and the present, joined to add value for our clients and legal certainty to their investments.\n\nOnassis & Baronetto advises companies and investors on RIGI, energy, mining, agribusiness and investment structuring. Write to [onassisbaronettolawyers@gmail.com](mailto:onassisbaronettolawyers@gmail.com) or meet the firm [on the portal]({url}).",
        "more": "See the full dashboard",
        "foot": "Sources: Argentine Energy Secretariat, BCRA, INDEC, Official Gazette, MAGyP, SIACAM, EIA. For information only; not financial advice.",
    },
    "pt": {
        "subject": "Argentina Invest Monitor · Semana de {d}",
        "intro": "Os dados públicos que marcaram a semana, organizados para investidores. Todos os números vêm de fontes oficiais e se atualizam sozinhos no portal.",
        "h_vm": "Vaca Muerta",
        "vm_oil": "**Petróleo:** {v} barris por dia em {p}, {y} na comparação anual.",
        "vm_gas": "**Gás:** {v} milhões de m³ por dia, {y} na comparação anual.",
        "vm_share": "**Peso nacional:** {v} do petróleo do país vem de Vaca Muerta.",
        "vm_wells": "**Poços:** {a} ativos; {n} poços novos nos últimos doze meses.",
        "vm_frac": "**Fraturamento:** {v} etapas nos últimos doze meses, {y} na comparação anual.",
        "vm_price": "**Preço realizado em Neuquén:** USD {v} por barril em {p}.",
        "h_mk": "Mercados e macro",
        "mk_brent": "**Brent:** USD {b} · **WTI:** USD {w} (em {d}).",
        "mk_fx": "**Dólar atacado:** ARS {v} por dólar (em {d}), {y} na comparação anual.",
        "mk_res": "**Reservas do BCRA:** USD {v} milhões (em {d}), {c} em um ano.",
        "mk_cpi": "**Inflação:** {m} no mês e {y} em doze meses em {p}.",
        "mk_badlar": "**Taxa BADLAR:** {v} ao ano (há um ano, {y1}).",
        "h_rigi": "RIGI: projetos aprovados",
        "rigi_line": "**{proj}** · {co} · USD {usd} milhões · aprovado em {d}. [Boletim Oficial]({url})",
        "h_bo": "Boletim Oficial: normas da semana",
        "h_sec": "Outros setores",
        "sec_min": "**Mineração:** exportações de USD {v} milhões nos doze meses até {p}, {y} na comparação anual.",
        "sec_agro": "**Agro:** liquidação de divisas de USD {v} milhões nos doze meses até {p}, {y} na comparação anual.",
        "sec_ind": "**Indústria:** a produção industrial variou {y} na comparação anual em {p}.",
        "sec_act": "**Atividade:** o EMAE ficou em {v} pontos em {p} ({c} sobre o mês anterior).",
        "h_news": "Na imprensa",
        "news_note": "Manchetes em espanhol, como publicadas por cada veículo.",
        "h_firm": "Assessoria jurídica para investir na Argentina",
        "firm": "Com raízes na Grécia e em Córdoba, o escritório une uma tradição ligada aos negócios internacionais ao conhecimento do direito argentino. Tradição e atualidade unidas para agregar valor aos nossos clientes e segurança jurídica aos seus investimentos.\n\nOnassis & Baronetto assessora empresas e investidores em RIGI, energia, mineração, agronegócio e estruturação de investimentos. Escreva para [onassisbaronettolawyers@gmail.com](mailto:onassisbaronettolawyers@gmail.com) ou conheça o escritório [no portal]({url}).",
        "more": "Ver o painel completo",
        "foot": "Fontes: Secretaria de Energia, BCRA, INDEC, Boletim Oficial, MAGyP, SIACAM, EIA. Conteúdo informativo; não constitui assessoria financeira.",
    },
    "el": {
        "subject": "Argentina Invest Monitor · Εβδομάδα {d}",
        "intro": "Τα δημόσια στοιχεία που κινήθηκαν αυτή την εβδομάδα, οργανωμένα για επενδυτές. Όλοι οι αριθμοί προέρχονται από επίσημες πηγές και ενημερώνονται αυτόματα στην πύλη.",
        "h_vm": "Vaca Muerta",
        "vm_oil": "**Πετρέλαιο:** {v} βαρέλια ημερησίως τον {p}, {y} σε ετήσια βάση.",
        "vm_gas": "**Φυσικό αέριο:** {v} εκατ. m³ ημερησίως, {y} σε ετήσια βάση.",
        "vm_share": "**Εθνικό μερίδιο:** το {v} του πετρελαίου της χώρας προέρχεται από τη Vaca Muerta.",
        "vm_wells": "**Γεωτρήσεις:** {a} ενεργές· {n} νέες τους τελευταίους δώδεκα μήνες.",
        "vm_frac": "**Υδραυλική ρωγμάτωση:** {v} στάδια τους τελευταίους δώδεκα μήνες, {y} σε ετήσια βάση.",
        "vm_price": "**Τιμή πώλησης στο Neuquén:** USD {v} ανά βαρέλι τον {p}.",
        "h_mk": "Αγορές και μακροοικονομία",
        "mk_brent": "**Brent:** USD {b} · **WTI:** USD {w} (στις {d}).",
        "mk_fx": "**Δολάριο χονδρικής:** ARS {v} ανά δολάριο (στις {d}), {y} σε ετήσια βάση.",
        "mk_res": "**Αποθεματικά Κεντρικής Τράπεζας:** USD {v} εκατ. (στις {d}), {c} σε ένα έτος.",
        "mk_cpi": "**Πληθωρισμός:** {m} μηνιαίως και {y} ετησίως τον {p}.",
        "mk_badlar": "**Επιτόκιο BADLAR:** {v} ετησίως (πριν από ένα έτος, {y1}).",
        "h_rigi": "RIGI: εγκεκριμένα έργα",
        "rigi_line": "**{proj}** · {co} · USD {usd} εκατ. · εγκρίθηκε στις {d}. [Επίσημη Εφημερίδα]({url})",
        "h_bo": "Επίσημη Εφημερίδα: οι ρυθμίσεις της εβδομάδας",
        "h_sec": "Άλλοι τομείς",
        "sec_min": "**Εξόρυξη:** εξαγωγές USD {v} εκατ. στο δωδεκάμηνο έως {p}, {y} σε ετήσια βάση.",
        "sec_agro": "**Γεωργία:** ρευστοποίηση συναλλάγματος USD {v} εκατ. στο δωδεκάμηνο έως {p}, {y} σε ετήσια βάση.",
        "sec_ind": "**Βιομηχανία:** η βιομηχανική παραγωγή μεταβλήθηκε {y} σε ετήσια βάση τον {p}.",
        "sec_act": "**Δραστηριότητα:** ο δείκτης EMAE ήταν {v} μονάδες τον {p} ({c} σε μηνιαία βάση).",
        "h_news": "Στον Τύπο",
        "news_note": "Τίτλοι στα ισπανικά, όπως δημοσιεύθηκαν από κάθε μέσο.",
        "h_firm": "Νομική υποστήριξη για επενδύσεις στην Αργεντινή",
        "firm": "Με ρίζες στην Ελλάδα και στην Κόρδοβα, το γραφείο συνδυάζει μια παράδοση συνδεδεμένη με τις διεθνείς επιχειρήσεις με τη γνώση του αργεντίνικου δικαίου. Παράδοση και σύγχρονη πραγματικότητα μαζί, για να προσθέτουμε αξία στους πελάτες μας και ασφάλεια δικαίου στις επενδύσεις τους.\n\nΗ Onassis & Baronetto συμβουλεύει εταιρείες και επενδυτές σε θέματα RIGI, ενέργειας, εξόρυξης, γεωργίας και δόμησης επενδύσεων. Γράψτε στο [onassisbaronettolawyers@gmail.com](mailto:onassisbaronettolawyers@gmail.com) ή γνωρίστε το γραφείο [στην πύλη]({url}).",
        "more": "Δείτε τον πλήρη πίνακα",
        "foot": "Πηγές: Υπουργείο Ενέργειας Αργεντινής, BCRA, INDEC, Επίσημη Εφημερίδα, MAGyP, SIACAM, EIA. Μόνο για ενημέρωση· δεν αποτελεί χρηματοοικονομική συμβουλή.",
    },
}


def load(name):
    try:
        return json.loads((DATA / name).read_text())
    except Exception as e:
        print(f"Aviso: no pude leer {name}: {e}", file=sys.stderr)
        return {}


def g(d, *keys):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int) and -len(d) <= k < len(d):
            d = d[k]
        else:
            return None
    return d


def num(v, lang, dec=0):
    if v is None:
        return None
    s = f"{v:,.{dec}f}"
    if lang == "en":
        return s
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def pct(v, lang, signed=True, dec=1):
    if v is None:
        return None
    s = num(abs(v), lang, dec)
    sign = ("+" if v > 0 else "−" if v < 0 else "") if signed else ("−" if v < 0 else "")
    return f"{sign}{s}%"


def period(p, lang):
    """'2026-08' → 'ago 2026'."""
    if not p:
        return None
    y, m = p[:7].split("-")
    return f"{MONTHS[lang][int(m) - 1]} {y}"


def day(d, lang):
    if not d:
        return None
    dt = date.fromisoformat(d[:10])
    if lang == "en":
        return f"{MONTHS[lang][dt.month - 1]} {dt.day}, {dt.year}"
    return f"{dt.day} {MONTHS[lang][dt.month - 1]} {dt.year}"


def line(tpl, **kw):
    """Formatea solo si no falta ningún dato."""
    if any(v is None for v in kw.values()):
        return None
    return tpl.format(**kw)


def yoy(cur, prev):
    if cur is None or not prev:
        return None
    return (cur / prev - 1) * 100


def gather(today):
    vm, ex, fn, mn, ag, ind = (load(f) for f in
                               ["vm.json", "extras.json", "finance.json", "mining.json", "agro.json", "industry.json"])
    week_ago = (today - timedelta(days=7)).isoformat()
    month_ago = (today - timedelta(days=31)).isoformat()

    regs = [r for r in g(ex, "regulations", "items") or [] if (r.get("date") or "") >= week_ago]
    regs.sort(key=lambda r: r.get("date", ""), reverse=True)

    rigi_all = g(ex, "rigi_approvals") or []
    rigi_new = [r for r in rigi_all if (r.get("date") or "") >= month_ago]

    news = [n for n in g(ex, "news", "items") or [] if (n.get("published") or "")[:10] >= week_ago]
    news.sort(key=lambda n: n.get("published", ""), reverse=True)

    neuq = g(ex, "royalties", "price_usd_bbl", "Neuquén") or []
    infl = g(fn, "bcra", "inflation", "monthly") or []
    act = g(fn, "activity", "monthly") or []
    ipi = g(ind, "ipi", "original") or []

    return {
        "vm": vm, "ex": ex, "fn": fn, "mn": mn, "ag": ag, "ind": ind,
        "regs": regs[:6], "rigi_new": rigi_new, "rigi_all": rigi_all, "news": news[:5],
        "neuq": neuq[-1] if neuq else None,
        "infl": infl[-1] if infl else None,
        "act": act[-2:] if len(act) >= 2 else None,
        "ipi_period": ipi[-1]["period"] if ipi else None,
    }


def render(D, lang, today):
    t = T[lang]
    k = g(D["vm"], "kpis") or {}
    q = f"?lang={lang}"
    out = [t["intro"], ""]

    def section(title, lines, link=None):
        lines = [l for l in lines if l]
        if not lines:
            return
        out.append(f"## {title}")
        out.append("")
        out.extend(f"- {l}" for l in lines)
        if link:
            out.append("")
            out.append(f"[{t['more']} →]({SITE}{link}{q})")
        out.append("")

    vp = period(g(D["vm"], "latest_period"), lang)
    fr = g(D["ex"], "fracking") or {}
    nq = D["neuq"] or {}
    section(t["h_vm"], [
        line(t["vm_oil"], v=num(k.get("oil_bbl_d"), lang), p=vp, y=pct(k.get("oil_yoy_pct"), lang)),
        line(t["vm_gas"], v=num(k.get("gas_mmm3_d"), lang, 1), y=pct(k.get("gas_yoy_pct"), lang)),
        line(t["vm_share"], v=pct(k.get("national_oil_share_pct"), lang, signed=False)),
        line(t["vm_wells"], a=num(k.get("active_wells"), lang), n=num(k.get("new_wells_12m"), lang)),
        line(t["vm_frac"], v=num(fr.get("stages_12m"), lang), y=pct(fr.get("stages_12m_yoy_pct"), lang)),
        line(t["vm_price"], v=num(nq.get("usd_bbl"), lang, 2), p=period(nq.get("period"), lang)),
    ], "/vaca-muerta/")

    bcra = g(D["fn"], "bcra") or {}
    brent, wti = g(D["ex"], "oil_price", "brent") or {}, g(D["ex"], "oil_price", "wti") or {}
    fx = g(D["ex"], "fx") or {}
    res = bcra.get("reserves") or {}
    res_v, res_y1 = g(res, "latest", "v"), res.get("y1")
    res_chg = None if res_v is None or res_y1 is None else res_v - res_y1
    res_chg_s = None if res_chg is None else ("+" if res_chg >= 0 else "−") + "USD " + num(abs(res_chg), lang) + " " + MILLION[lang]
    bad = g(bcra, "rates", "badlar") or {}
    inf = D["infl"] or {}
    section(t["h_mk"], [
        line(t["mk_brent"], b=num(brent.get("usd_bbl"), lang, 2), w=num(wti.get("usd_bbl"), lang, 2), d=day(brent.get("date"), lang)),
        line(t["mk_fx"], v=num(g(fx, "latest", "ars_per_usd"), lang, 2), d=day(g(fx, "latest", "date"), lang), y=pct(fx.get("yoy_pct"), lang)),
        line(t["mk_res"], v=num(res_v, lang), d=day(g(res, "latest", "date"), lang), c=res_chg_s),
        line(t["mk_cpi"], m=pct(inf.get("m"), lang, signed=False), y=pct(inf.get("y"), lang, signed=False), p=period(inf.get("period"), lang)),
        line(t["mk_badlar"], v=pct(g(bad, "latest", "v"), lang, signed=False), y1=pct(bad.get("y1"), lang, signed=False)),
    ], "/finanzas/")

    if D["rigi_new"]:
        rl = [line(t["rigi_line"], proj=r.get("project") or r.get("title"), co=r.get("company") or "—",
                   usd=num(r.get("usd_million"), lang), d=day(r.get("date"), lang), url=r.get("url"))
              for r in D["rigi_new"]]
        section(t["h_rigi"], rl)

    if D["regs"]:
        rl = []
        for r in D["regs"]:
            s = f"**{day(r.get('date'), lang)}** · [{r.get('title')}]({r.get('url')})"
            if r.get("agency"):
                s += f" · {nice_case(r['agency'])}"
            if lang == "es" and r.get("summary"):
                summ = r["summary"]
                s += f"  \n  {summ[:220].rstrip()}{'…' if len(summ) > 220 and not summ[:220].endswith('…') else ''}"
            rl.append(s)
        section(t["h_bo"], rl)

    me = g(D["mn"], "exports") or {}
    fs = g(D["ag"], "fx_settlements") or {}
    ipi = g(D["ind"], "ipi") or {}
    act = D["act"]
    act_line = None
    if act:
        act_line = line(t["sec_act"], v=num(act[1]["v"], lang, 1), p=period(act[1]["period"], lang),
                        c=pct(yoy(act[1]["v"], act[0]["v"]), lang))
    section(t["h_sec"], [
        line(t["sec_min"], v=num(me.get("last_12m"), lang), p=period(me.get("latest_period"), lang),
             y=pct(yoy(me.get("last_12m"), me.get("prev_12m")), lang)),
        line(t["sec_agro"], v=num(fs.get("last_12m"), lang), p=period(fs.get("latest_period"), lang),
             y=pct(yoy(fs.get("last_12m"), fs.get("prev_12m")), lang)),
        line(t["sec_ind"], y=pct(ipi.get("yoy"), lang), p=period(D["ipi_period"], lang)),
        act_line,
    ], "/")

    if D["news"]:
        out.append(f"## {t['h_news']}")
        out.append("")
        if t["news_note"]:
            out.append(f"_{t['news_note']}_")
            out.append("")
        out.extend(f"- [{n['title']}]({n['url']}) · {n.get('source', '')}" for n in D["news"])
        out.append("")

    out += ["---", "", f"## {t['h_firm']}", "", t["firm"].format(url=f"{SITE}/estudio/{q}"), "",
            "---", "", f"_{t['foot']}_", ""]
    monday = today - timedelta(days=today.weekday())
    subject = t["subject"].format(d=day(monday.isoformat(), lang))
    return subject, "\n".join(out)


# ---------- Buttondown ----------

def bd(method, path, key, **kw):
    r = requests.request(method, f"{API}{path}", headers={"Authorization": f"Token {key}"}, timeout=30, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Buttondown {method} {path}: {r.status_code} {r.text[:300]}")
    return r.json() if r.text else {}


def tag_ids(key):
    ids, url = {}, "/tags"
    while url:
        data = bd("GET", url, key)
        for tg in data.get("results", []):
            ids[tg["name"]] = tg["id"]
        nxt = data.get("next")
        url = nxt.replace(API, "") if nxt else None
    return ids


def existing_issues(key):
    seen = set()
    for status in ("draft", "scheduled", "sent", "about_to_send"):
        try:
            data = bd("GET", "/emails", key, params={"status": status})
        except RuntimeError:
            continue
        for em in data.get("results", []):
            iss = (em.get("metadata") or {}).get("aim_issue")
            if iss:
                seen.add(iss)
    return seen


def upload(issues, issue_id):
    key = os.environ.get("BUTTONDOWN_API_KEY", "").strip()
    if not key:
        print("Sin BUTTONDOWN_API_KEY: solo se guardaron los archivos.")
        return
    status = "about_to_send" if os.environ.get("NEWSLETTER_STATUS") == "send" else "draft"
    tags = tag_ids(key)
    seen = existing_issues(key)
    for lang, (subject, body) in issues.items():
        iss = f"{issue_id}-{lang}"
        if iss in seen:
            print(f"{lang}: la edición {iss} ya existe en Buttondown, no la duplico.")
            continue
        tag = tags.get(f"lang-{lang}")
        if not tag:
            print(f"{lang}: no hay suscriptores con la etiqueta lang-{lang}; no creo el correo.")
            continue
        payload = {
            "subject": subject,
            "body": "<!-- buttondown-editor-mode: plaintext -->\n" + body,
            "status": status,
            "metadata": {"aim_issue": iss},
            "filters": {"predicate": "and", "groups": [],
                        "filters": [{"field": "subscriber.tags", "operator": "contains", "value": tag}]},
        }
        em = bd("POST", "/emails", key, json=payload)
        print(f"{lang}: creado en Buttondown como {status} ({em.get('id')}).")


def main():
    today = date.fromisoformat(os.environ["NEWSLETTER_DATE"]) if os.environ.get("NEWSLETTER_DATE") else datetime.now().date()
    y, w, _ = today.isocalendar()
    issue_id = f"{y}-W{w:02d}"
    D = gather(today)
    folder = OUT / issue_id
    folder.mkdir(parents=True, exist_ok=True)
    issues = {}
    for lang in LANGS:
        subject, body = render(D, lang, today)
        issues[lang] = (subject, body)
        (folder / f"{lang}.md").write_text(f"# {subject}\n\n{body}")
    print(f"Edición {issue_id} guardada en {folder.relative_to(ROOT)}")
    upload(issues, issue_id)


if __name__ == "__main__":
    main()
