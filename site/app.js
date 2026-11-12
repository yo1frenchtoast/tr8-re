import { build, extractUpdate } from "./tr8patch.js";

const FR = {
  "nav.github": "Source",
  "hero.kicker": "Rhythm performer · système v1.61",
  "hero.title": "De nouvelles fonctions pour votre TR-8",
  "hero.lede": "Choisissez vos mods, déposez le fichier de mise à jour officiel de Roland, et récupérez un TR8_UPD.BIN modifié à installer avec la procédure de mise à jour habituelle. Tout se passe dans votre navigateur.",
  "mod.title": "Choisir les mods",
  "mod.hint": "Cochez un mod ou les deux : les deux ensemble donnent un seul firmware qui contient les deux.",
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
  "faq.q4": "Où sont mes mouvements ou mes longueurs après un redémarrage ?",
  "faq.a4": "Les longueurs sont sauvegardées avec chaque pattern. Les mouvements de motion restent en RAM pour l'instant : ils sont perdus à l'extinction.",
  "foot.affil": "Projet non officiel, sans lien avec Roland Corporation ni approuvé par elle. TR-8 est une marque de Roland Corporation.",
  "foot.license": "Licence MIT. Aucun code Roland n'est inclus : la page modifie le fichier que vous fournissez.",
  "foot.docs": "Documentation et source",
};
const MSG = {
  en: { tested: "Tested on a TR-8", experimental: "Experimental", doc: "How it works", loaded: "loaded", building: "Building…",
        built: "Done. Download the file, then install it (step 4).", progress: "compressing" },
  fr: { tested: "Testé sur TR-8", experimental: "Expérimental", doc: "Fonctionnement", loaded: "chargé", building: "Construction…",
        built: "Terminé. Téléchargez le fichier, puis installez-le (étape 4).", progress: "compression" },
};
const REPO = "https://github.com/yo1frenchtoast/tr8-re/blob/main/";

const $ = (id) => document.getElementById(id);
const EN = {};
document.querySelectorAll("[data-i18n]").forEach((el) => (EN[el.dataset.i18n] = el.textContent));

let lang = "en", manifest = null, input = null, fileName = "", output = null;
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
  if (input) $("drop-text").textContent = `${fileName} · ${MSG[lang].loaded}`;
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
  const box = $("mods"), sel = box.children.length ? checked() : features().map(([, p]) => p.provides[0]);
  box.replaceChildren();
  for (const [, p] of features()) {
    const card = $("mod-card").content.firstElementChild.cloneNode(true);
    const cb = card.querySelector("input");
    cb.value = p.provides[0];
    cb.checked = sel.includes(cb.value);
    cb.addEventListener("change", refresh);
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

function log(text, cls) {
  const line = document.createElement("span");
  line.textContent = text + "\n";
  if (cls) line.className = cls;
  $("log").append(line);
  $("log").scrollTop = $("log").scrollHeight;
}

function refresh() {
  output = null;
  $("download").hidden = true;
  const name = manifest && pickPatch();
  $("build").disabled = !(name && input && $("accept").checked);
}

async function takeFile(file) {
  const drop = $("drop");
  drop.classList.remove("ok", "bad");
  $("log").replaceChildren();
  input = null;
  try {
    input = await extractUpdate(new Uint8Array(await file.arrayBuffer()));
    fileName = file.name;
    drop.classList.add("ok");
    $("drop-text").textContent = `${fileName} · ${MSG[lang].loaded}`;
  } catch (e) {
    drop.classList.add("bad");
    $("drop-text").textContent = String(e.message || e);
  }
  refresh();
}

async function run() {
  const name = pickPatch();
  $("build").disabled = true;
  $("log").replaceChildren();
  $("meter").hidden = false;
  $("meter-bar").style.width = "0";
  log(`${MSG[lang].building} ${manifest.patches[name].provides.join(" + ")}`);
  try {
    await new Promise((r) => setTimeout(r, 30));            // let the page repaint first
    output = await build(input, manifest, [name], {
      log: (t) => log(t),
      progress: (f) => ($("meter-bar").style.width = `${Math.round(f * 100)}%`),
    });
    $("meter-bar").style.width = "100%";
    log(MSG[lang].built, "ok");
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

manifest = await (await fetch("patches.json")).json();
setLang(lang);
refresh();
