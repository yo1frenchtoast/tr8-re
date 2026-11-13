import { build, extractUpdate } from "./tr8patch.js";
import { TUTORIALS } from "./tutorials.js";

const FR = {
  "nav.github": "Source",
  "hero.kicker": "Rhythm performer · système v1.61",
  "hero.title": "De nouvelles fonctions pour votre TR-8",
  "hero.lede": "Choisissez vos mods, déposez le fichier de mise à jour officiel de Roland, et récupérez un TR8_UPD.BIN modifié à installer avec la procédure de mise à jour habituelle. Tout se passe dans votre navigateur.",
  "mod.title": "Choisir les mods",
  "mod.hint": "Cochez un ou plusieurs mods : le fichier construit contient exactement ceux-là.",
  "file.title": "Charger la mise à jour officielle",
  "file.hint1": "Téléchargez",
  "file.hint2": "depuis",
  "file.roland": "la page support TR-8 de Roland",
  "file.hint3": ", puis déposez ici le zip ou le TR8_UPD.BIN qu'il contient.",
  "file.drop": "Déposez tr8_sys_v161.zip ou TR8_UPD.BIN, ou cliquez pour choisir",
  "file.privacy": "Le fichier est lu uniquement dans cette page. Rien n'est envoyé et aucun firmware Roland n'est fourni ici.",
  "build.title": "Construire",
  "build.accept": "J'ai sauvegardé mes patterns et kits (sauvegarde USB), je garde le fichier officiel pour revenir en arrière, et je flashe à mes risques.",
  "build.button": "Construire TR8_UPD.BIN",
  "build.download": "Télécharger TR8_UPD.BIN",
  "install.title": "Installer sur la TR-8",
  "install.s1": "Maintenez le pad [1] et allumez la TR-8. Les boutons d'instruments BD à RC clignotent.",
  "install.s2": "Branchez le câble USB. Un lecteur nommé TR-8 apparaît.",
  "install.s3": "Copiez uniquement TR8_UPD.BIN à la racine du lecteur (le nom doit être exactement TR8_UPD.BIN).",
  "install.s4": "Éjectez le lecteur, puis débranchez le câble USB. SD et le pas [2] clignotent.",
  "install.s5": "Appuyez sur le pad [2]. N'éteignez pas pendant l'écriture.",
  "install.s6": "Quand BD à RC et tous les pas clignotent, c'est terminé : éteignez et rallumez.",
  "install.back": "Pour revenir en arrière, faites la même chose avec le TR8_UPD.BIN officiel du zip.",
  "faq.title": "Un problème ?",
  "faq.q1": "La page refuse mon fichier",
  "faq.a1": "Seul le système officiel v1.61, non modifié, est pris en charge. Retéléchargez le zip chez Roland. Un fichier déjà modifié par cette page est refusé exprès : partez toujours du fichier officiel.",
  "faq.q2": "La TR-8 ne démarre pas, ou se comporte mal",
  "faq.a2": "Maintenez le pad [1] à l'allumage : le programme de mise à jour démarre avant le firmware, même modifié. Installez le TR8_UPD.BIN officiel, puis restaurez votre sauvegarde si besoin.",
  "faq.q3": "La mise à jour s'arrête sur l'erreur 6",
  "faq.a3": "Le fichier sur le lecteur n'est pas celui construit ici (somme de contrôle). Reconstruisez-le, recopiez-le, et vérifiez qu'il n'y a rien d'autre sur le lecteur.",
  "faq.q4": "Où sont mes mouvements, longueurs ou mesures après un redémarrage ?",
  "faq.a4": "Les longueurs sont sauvegardées avec chaque pattern, et les mesures de la chaîne de mesures dans la mémoire flash de la TR-8 : les deux survivent à l'extinction. Les mouvements de motion restent en RAM pour l'instant : ils sont perdus à l'extinction.",
  "guide.title": "Comment les utiliser",
  "guide.hint": "Chaque mod fonctionne de la même façon quand plusieurs sont construits ensemble.",
  "foot.affil": "Projet non officiel, sans lien avec Roland Corporation ni approuvé par elle. TR-8 est une marque de Roland Corporation.",
  "foot.license": "Licence MIT. Aucun code Roland n'est inclus : la page modifie le fichier que vous fournissez.",
  "foot.docs": "Documentation et source",
};
const MSG = {
  en: { tested: "Tested on a TR-8", experimental: "Experimental", doc: "How it works", loaded: "loaded", building: "Building…",
        built: "Done. Download the file, then install it (step 4).", progress: "compressing",
        first: "First session", gestures: "Gestures", notes: "Good to know", fulldoc: "Full documentation",
        gesture: "Gesture", result: "Result" },
  fr: { tested: "Testé sur TR-8", experimental: "Expérimental", doc: "Fonctionnement", loaded: "chargé", building: "Construction…",
        built: "Terminé. Téléchargez le fichier, puis installez-le (étape 4).", progress: "compression",
        first: "Premier essai", gestures: "Gestes", notes: "Bon à savoir", fulldoc: "Documentation complète",
        gesture: "Geste", result: "Résultat" },
};
const REPO = "https://github.com/yo1frenchtoast/tr8-re/blob/main/";

// tr8patch.js reports in English (it is shared with tests/site_check.mjs). Its messages are
// translated here; the technical lines (sections, addresses, sites) stay as they are.
const FR_MSG = [
  [/^input: TR-8 v1\.61 TR8_UPD\.BIN, all checks OK$/, "entrée : TR8_UPD.BIN de TR-8 v1.61, toutes les vérifications sont OK"],
  [/^compressing the application\.\.\.$/, "compression de l'application..."],
  [/^output checked: trailer and module sums OK$/, "sortie vérifiée : fin de fichier et sommes des modules OK"],
  [/^file too small: not a TR-8 TR8_UPD\.BIN$/, "fichier trop petit : ce n'est pas un TR8_UPD.BIN de TR-8"],
  [/^unexpected trailer: not a TR-8 v1\.61 TR8_UPD\.BIN$/, "fin de fichier inattendue : ce n'est pas un TR8_UPD.BIN de TR-8 v1.61"],
  [/^module at (0x[0-9a-f]+): byte-sum is wrong \(corrupted file\)$/, "module en $1 : somme de contrôle fausse (fichier corrompu)"],
  [/^unsupported application "(.*)": only system v(.+) is supported$/, "application non prise en charge « $1 » : seul le système v$2 est pris en charge"],
  [/^the application does not match the official v1\.61 \(already patched, or another version\)$/,
   "l'application ne correspond pas à la v1.61 officielle (fichier déjà modifié, ou autre version)"],
  [/^unexpected bytes at (0x[0-9a-f]+) \(patches cannot be combined\?\)$/, "octets inattendus en $1 (patches incompatibles ?)"],
  [/^payload (.+) outside the free regions$/, "payload $1 en dehors des zones libres"],
  [/^payload (.+) overlaps a protected range$/, "payload $1 sur une zone protégée"],
  [/^internal error: compressor round trip failed$/, "erreur interne : la recompression a échoué"],
  [/^patched application too big$/, "application modifiée trop grande"],
  [/^unknown patch (.+)$/, "patch inconnu $1"],
  [/^these patches use the same free memory and cannot be combined$/, "ces patches utilisent la même mémoire libre et ne peuvent pas être combinés"],
  [/^zip file not readable$/, "fichier zip illisible"],
  [/^zip compression method not supported$/, "méthode de compression du zip non prise en charge"],
  [/^no TR8_UPD\.BIN inside this zip$/, "aucun TR8_UPD.BIN dans ce zip"],
];
function tr(text) {
  if (lang !== "fr") return text;
  for (const [re, fr] of FR_MSG) if (re.test(text)) return text.replace(re, fr);
  return text;
}

const $ = (id) => document.getElementById(id);
const EN = {};
document.querySelectorAll("[data-i18n]").forEach((el) => (EN[el.dataset.i18n] = el.textContent));

let lang = "en", manifest = null, input = null, fileName = "", output = null, guideTab = null;
let dropError = null;      // last file error, in English (translated when shown)
const logLines = [];       // build log: { text, cls }; text is English or a function of the language
try { lang = localStorage.getItem("lang") || (navigator.language.startsWith("fr") ? "fr" : "en"); } catch { /* storage blocked */ }

function setLang(l) {
  lang = l;
  try { localStorage.setItem("lang", l); } catch { /* ignore */ }
  document.documentElement.lang = l;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const k = el.dataset.i18n;
    el.textContent = (l === "fr" ? FR[k] : EN[k]) ?? EN[k];
  });
  document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === l)));
  renderMods();
  renderGuide();
  showDrop();
  renderLog();
}

function showDrop() {
  if (input) $("drop-text").textContent = `${fileName} · ${MSG[lang].loaded}`;
  else if (dropError) $("drop-text").textContent = tr(dropError);
}

// One card per feature (patches that give a single feature). The build uses the
// patch whose features are exactly the checked ones (motion + poly -> motion-poly).
function features() {
  return Object.entries(manifest.patches).filter(([, p]) => p.provides.length === 1);
}

function checked() {
  return [...$("mods").querySelectorAll("input:checked")].map((i) => i.value);
}

function pickPatch() {
  const want = checked().sort().join("+");
  if (!want) return null;
  const hit = Object.entries(manifest.patches).find(([, p]) => [...p.provides].sort().join("+") === want);
  return hit ? hit[0] : null;
}

function renderMods() {
  if (!manifest) return;
  const box = $("mods"), sel = box.children.length ? checked()
    : features().filter(([, p]) => p.status === "tested").map(([, p]) => p.provides[0]);
  box.replaceChildren();
  for (const [, p] of features()) {
    const card = $("mod-card").content.firstElementChild.cloneNode(true);
    const cb = card.querySelector("input");
    cb.value = p.provides[0];
    cb.checked = sel.includes(cb.value);
    cb.addEventListener("change", () => {
      if (cb.checked) guideTab = cb.value;          // show the tutorial of the mod just ticked
      refresh();
    });
    card.querySelector(".mod-title").textContent = p.title[lang];
    card.querySelector(".mod-text").textContent = p.text[lang];
    const tag = card.querySelector(".tag");
    tag.textContent = MSG[lang][p.status === "tested" ? "tested" : "experimental"];
    tag.classList.toggle("exp", p.status !== "tested");
    const doc = card.querySelector(".mod-doc");
    doc.href = REPO + p.doc;
    doc.textContent = `${MSG[lang].doc} →`;
    box.append(card);
  }
}

// Tutorial text: [[X]] is a TR-8 button or control, {{X}} is display text. Built with DOM nodes
// (no innerHTML), so the strings stay plain text.
function rich(text) {
  const frag = document.createDocumentFragment();
  for (const part of text.split(/(\[\[.+?\]\]|\{\{.+?\}\})/)) {
    if (!part) continue;
    const m = part.match(/^\[\[(.+)\]\]$/) || part.match(/^\{\{(.+)\}\}$/);
    if (!m) { frag.append(part); continue; }
    const el = document.createElement(part[0] === "[" ? "kbd" : "samp");
    el.textContent = m[1];
    frag.append(el);
  }
  return frag;
}

function el(tag, cls, ...kids) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  e.append(...kids);
  return e;
}

// One tab per ticked mod, in the order of the cards, right under them. The mod ticked last is
// open; a tab the user picked stays open. Nothing ticked: no tutorial.
function renderGuide() {
  if (!manifest) return;
  const sel = checked();
  const ids = features().map(([, p]) => p.provides[0]).filter((f) => TUTORIALS[f] && sel.includes(f));
  $("guide-wrap").hidden = !ids.length;
  if (!ids.length) return;
  if (!ids.includes(guideTab)) guideTab = ids[0];
  const tabs = $("guide-tabs");
  tabs.replaceChildren();
  for (const id of ids) {
    const b = el("button", "tab", TUTORIALS[id][lang].tab);
    b.type = "button";
    b.id = `tab-${id}`;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", String(id === guideTab));
    b.setAttribute("aria-controls", "guide");
    b.tabIndex = id === guideTab ? 0 : -1;
    b.addEventListener("click", () => { guideTab = id; renderGuide(); });
    b.addEventListener("keydown", (e) => {
      const d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!d) return;
      guideTab = ids[(ids.indexOf(id) + d + ids.length) % ids.length];
      renderGuide();
      $(`tab-${guideTab}`).focus();
    });
    tabs.append(b);
  }
  const t = TUTORIALS[guideTab], c = t[lang], m = MSG[lang];
  const body = $("guide");
  body.setAttribute("aria-labelledby", `tab-${guideTab}`);
  body.replaceChildren();
  if (c.warn) body.append(el("p", "warn", rich(c.warn)));
  body.append(el("p", "intro", rich(c.intro)));
  body.append(el("h3", null, m.first), el("ol", "howto", ...c.steps.map((s) => el("li", null, rich(s)))));
  const table = el("div", "gestures");
  table.setAttribute("role", "table");
  const head = el("div", "g-row g-head", el("span", null, m.gesture), el("span", null, m.result));
  head.setAttribute("role", "row");
  [...head.children].forEach((x) => x.setAttribute("role", "columnheader"));
  table.append(head);
  for (const [g, r] of c.gestures) {
    const row = el("div", "g-row", el("span", "g-do", rich(g)), el("span", "g-res", rich(r)));
    row.setAttribute("role", "row");
    [...row.children].forEach((x) => x.setAttribute("role", "cell"));
    table.append(row);
  }
  body.append(el("h3", null, m.gestures), table);
  body.append(el("h3", null, m.notes), el("ul", "notes", ...c.notes.map((s) => el("li", null, rich(s)))));
  const doc = el("a", "mod-doc", `${m.fulldoc} →`);
  doc.href = REPO + t.doc;
  doc.target = "_blank";
  doc.rel = "noopener";
  body.append(el("p", "more", doc));
}

function log(text, cls) {
  logLines.push({ text, cls });
  renderLog();
}

function renderLog() {
  $("log").replaceChildren(...logLines.map(({ text, cls }) => {
    const line = document.createElement("span");
    line.textContent = (typeof text === "function" ? text() : tr(text)) + "\n";
    if (cls) line.className = cls;
    return line;
  }));
  $("log").scrollTop = $("log").scrollHeight;
}

function refresh() {
  renderGuide();
  output = null;
  $("download").hidden = true;
  const name = manifest && pickPatch();
  $("build").disabled = !(name && input && $("accept").checked);
}

async function takeFile(file) {
  const drop = $("drop");
  drop.classList.remove("ok", "bad");
  logLines.length = 0;
  renderLog();
  input = null;
  dropError = null;
  try {
    input = await extractUpdate(new Uint8Array(await file.arrayBuffer()));
    fileName = file.name;
    drop.classList.add("ok");
  } catch (e) {
    drop.classList.add("bad");
    dropError = String(e.message || e);
  }
  showDrop();
  refresh();
}

async function run() {
  const name = pickPatch();
  $("build").disabled = true;
  logLines.length = 0;
  $("meter").hidden = false;
  $("meter-bar").style.width = "0";
  const what = manifest.patches[name].provides.join(" + ");
  log(() => `${MSG[lang].building} ${what}`);
  try {
    await new Promise((r) => setTimeout(r, 30));            // let the page repaint first
    output = await build(input, manifest, [name], {
      log: (t) => log(t),
      progress: (f) => ($("meter-bar").style.width = `${Math.round(f * 100)}%`),
    });
    $("meter-bar").style.width = "100%";
    log(() => MSG[lang].built, "ok");
    $("download").hidden = false;
  } catch (e) {
    log(String(e.message || e), "err");
  }
  $("build").disabled = false;
}

function download() {
  const url = URL.createObjectURL(new Blob([output], { type: "application/octet-stream" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: "TR8_UPD.BIN" });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

$("file").addEventListener("change", (e) => e.target.files[0] && takeFile(e.target.files[0]));
const drop = $("drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => { e.preventDefault(); e.dataTransfer.files[0] && takeFile(e.dataTransfer.files[0]); });
$("accept").addEventListener("change", refresh);
$("build").addEventListener("click", run);
$("download").addEventListener("click", download);
document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));

// GitHub Pages sends max-age=600: revalidate so a new status or payload shows at once.
manifest = await (await fetch("patches.json", { cache: "no-cache" })).json();
setLang(lang);
refresh();
