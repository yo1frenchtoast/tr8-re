// Tutorials shown in the "Use your mods" section, one per feature (the "provides" names of
// patches.json). Source: docs/MOTION.md, docs/POLY.md, docs/CHAIN.md ("Use"); keep them in step.
// Markup in the strings: [[X]] is a button or control on the TR-8, {{X}} is display text.

export const TUTORIALS = {
  motion: {
    doc: "docs/MOTION.md",
    en: {
      tab: "Motion",
      intro: "Record knob and fader moves on the steps of the pattern. The TR-8 plays them back on every pass.",
      steps: [
        "Start a pattern.",
        "Hold [[TR-REC]] and turn a knob during one pass, for example the BD [[TUNE]] knob. Release [[TR-REC]].",
        "Listen: on every pass, the knob moves by itself on the steps where you turned it.",
        "To change the move, hold [[TR-REC]] and turn the knob again. The new values replace the old ones.",
        "To erase the move, hold [[CLEAR]] and turn the knob. The knob still changes the sound.",
      ],
      gestures: [
        ["[[TR-REC]] + move a control, while playing", "The value is stored on the current step"],
        ["[[CLEAR]] + move a control", "The motion of that control is erased (variations A and B)"],
        ["Move a control, no button held", "Live change only: the recorded motion continues"],
      ],
      notes: [
        "All 49 controls can record: 36 knobs, 11 level faders, shuffle and fine tempo.",
        "Each control has 16 steps for variation A and 16 for variation B.",
        "There is one motion for all patterns: a pattern change keeps the same moves.",
        "While you record, the control you touch stops its playback for 2 steps after each touch.",
        "Motion is kept in RAM only: it is lost when you switch off.",
      ],
    },
    fr: {
      tab: "Motion",
      intro: "Enregistrez les mouvements des potentiomètres et des faders sur les pas du pattern. La TR-8 les rejoue à chaque passage.",
      steps: [
        "Lancez un pattern.",
        "Maintenez [[TR-REC]] et tournez un potentiomètre pendant un passage, par exemple [[TUNE]] du BD. Relâchez [[TR-REC]].",
        "Écoutez : à chaque passage, le potentiomètre bouge tout seul sur les pas où vous l'avez tourné.",
        "Pour refaire le mouvement, maintenez [[TR-REC]] et tournez à nouveau. Les nouvelles valeurs remplacent les anciennes.",
        "Pour effacer le mouvement, maintenez [[CLEAR]] et tournez le potentiomètre. Il change toujours le son.",
      ],
      gestures: [
        ["[[TR-REC]] + bouger une commande, en lecture", "La valeur est enregistrée sur le pas en cours"],
        ["[[CLEAR]] + bouger une commande", "Le motion de cette commande est effacé (variations A et B)"],
        ["Bouger une commande sans bouton", "Changement en direct seulement : le motion enregistré continue"],
      ],
      notes: [
        "Les 49 commandes peuvent enregistrer : 36 potentiomètres, 11 faders de niveau, le shuffle et le tempo fin.",
        "Chaque commande a 16 pas pour la variation A et 16 pour la variation B.",
        "Il y a un seul motion pour tous les patterns : changer de pattern garde les mêmes mouvements.",
        "Pendant l'enregistrement, la commande touchée arrête sa lecture pendant 2 pas après chaque mouvement.",
        "Le motion est en RAM seulement : il est perdu à l'extinction.",
      ],
    },
  },

  poly: {
    doc: "docs/POLY.md",
    en: {
      tab: "Polyrhythm",
      intro: "Give an instrument its own loop length. An instrument with length L plays its steps 1 to L in a loop, against the length of the pattern.",
      steps: [
        "On a 16-step pattern, put the closed hi-hat [[CH]] on step 1 only.",
        "Hold [[LAST STEP]] and [[CH]], then press pad [[3]]. The display shows {{L  3}}.",
        "Start the pattern: [[CH]] plays on every third step, 3 against 16.",
        "Hold [[LAST STEP]] + [[CH]] to see its length: the steps inside it are green and its position blinks.",
        "To go back to the pattern length, do the same gesture with the same pad again. The display shows {{LOFF}}.",
      ],
      gestures: [
        ["[[LAST STEP]] + instrument + pad n", "That instrument loops over n steps ({{L  n}})"],
        ["The same gesture, same pad again", "Back to the pattern length ({{LOFF}})"],
        ["[[LAST STEP]] + several instruments + pad n", "All of them get that length"],
        ["[[LAST STEP]] + pad n, no instrument", "As usual: sets the pattern length"],
      ],
      notes: [
        "The lengths are saved with each pattern, like any other edit. Variations A and B share them.",
        "Steps after L are not played, but they are kept.",
        "The global accent (AC) and the weak accent follow the pattern, not the instrument.",
        "Each instrument goes back to its step 1 when you start or stop.",
        "With scatter on, the instruments play as written.",
        "In TR-REC, [[LAST STEP]] blinks while the selected instrument has its own length.",
      ],
    },
    fr: {
      tab: "Polyrythme",
      intro: "Donnez à un instrument sa propre longueur de boucle. Un instrument de longueur L joue ses pas 1 à L en boucle, contre la longueur du pattern.",
      steps: [
        "Sur un pattern de 16 pas, placez le charleston fermé [[CH]] sur le pas 1 seulement.",
        "Maintenez [[LAST STEP]] et [[CH]], puis appuyez sur le pad [[3]]. L'écran affiche {{L  3}}.",
        "Lancez le pattern : [[CH]] joue tous les trois pas, 3 contre 16.",
        "Maintenez [[LAST STEP]] + [[CH]] pour voir sa longueur : les pas compris sont verts et sa position clignote.",
        "Pour revenir à la longueur du pattern, refaites le même geste avec le même pad. L'écran affiche {{LOFF}}.",
      ],
      gestures: [
        ["[[LAST STEP]] + instrument + pad n", "Cet instrument boucle sur n pas ({{L  n}})"],
        ["Le même geste, même pad", "Retour à la longueur du pattern ({{LOFF}})"],
        ["[[LAST STEP]] + plusieurs instruments + pad n", "Tous prennent cette longueur"],
        ["[[LAST STEP]] + pad n, sans instrument", "Comme d'habitude : règle la longueur du pattern"],
      ],
      notes: [
        "Les longueurs sont sauvegardées avec chaque pattern, comme toute autre modification. Les variations A et B les partagent.",
        "Les pas après L ne sont pas joués, mais ils sont gardés.",
        "L'accent global (AC) et l'accent faible suivent le pattern, pas l'instrument.",
        "Chaque instrument revient à son pas 1 au départ et à l'arrêt.",
        "Avec le scatter activé, les instruments jouent tels qu'écrits.",
        "En TR-REC, [[LAST STEP]] clignote quand l'instrument sélectionné a sa propre longueur.",
      ],
    },
  },

  chain: {
    doc: "docs/CHAIN.md",
    en: {
      tab: "Bar chain",
      intro: "Play a pattern as up to eight bars, each with its own A and B steps. A plays bars 1 to Na, B plays bars 1 to Nb, and A+B plays the A bars, then the B bars.",
      steps: [
        "Hold [[A]] and press pads [[1]] [[2]] [[3]] [[4]], one after the other. Side A is now 4 bars long. The display shows {{  A1}} to {{  A4}}.",
        "Select a bar with [[A]] + its pad, then record its steps as usual (step pads or [[TR-REC]]). Each bar keeps its own steps.",
        "Hold [[B]] and press pads [[1]] [[2]]: side B is 2 bars long. Record its steps the same way.",
        "Press [[A]] to play the A bars in order, [[B]] for the B bars, [[A]] + [[B]] for the A bars and then the B bars.",
        "While it plays, the step pads show the bar you hear. Hold [[A]] or [[B]] to see that side's bars: the bar that plays blinks yellow.",
        "Change pattern: each pattern has its own bars and lengths.",
      ],
      gestures: [
        ["[[A]] + pad 1–8", "Select bar n on its A steps. Side A becomes at least n bars ({{  An}})"],
        ["[[B]] + pad 1–8", "The same on the B steps ({{  Bn}})"],
        ["[[A]] or [[B]] + [[CLEAR]] + pad n", "That side becomes exactly n bars: use it to shorten"],
        ["[[A]] + [[B]] + pad n", "Both sides n bars ({{AB n}})"],
        ["[[A]] + [[B]] + [[CLEAR]] + any pad", "Both sides back to the normal pattern ({{AB--}})"],
      ],
      notes: [
        "A bar you never recorded plays the pattern itself, so a pattern sounds as before until you edit a bar.",
        "Selecting a bar is also a jump: while playing, it plays at the next bar boundary; stopped, the next start begins there.",
        "Shortening a side does not erase its bars: make the side longer again to get them back.",
        "Pads 9 to 16 stay normal step pads, and [[LAST STEP]] + pad keeps its normal and polyrhythm functions.",
        "The bars are saved in the flash of the TR-8 and survive power off. A Roland firmware update, or installing the official file, erases them.",
        "If the display shows {{FAIL}}, a bar was not saved: switch the TR-8 off and on, then check the bar.",
      ],
    },
    fr: {
      tab: "Chaîne de mesures",
      intro: "Jouez un pattern sur huit mesures maximum, chacune avec ses propres pas A et B. A joue les mesures 1 à Na, B les mesures 1 à Nb, et A+B joue les mesures A puis les mesures B.",
      steps: [
        "Maintenez [[A]] et appuyez sur les pads [[1]] [[2]] [[3]] [[4]], l'un après l'autre. Le côté A fait maintenant 4 mesures. L'écran affiche {{  A1}} à {{  A4}}.",
        "Choisissez une mesure avec [[A]] + son pad, puis enregistrez ses pas comme d'habitude (pads de pas ou [[TR-REC]]). Chaque mesure garde ses propres pas.",
        "Maintenez [[B]] et appuyez sur les pads [[1]] [[2]] : le côté B fait 2 mesures. Enregistrez ses pas de la même façon.",
        "Appuyez sur [[A]] pour jouer les mesures A dans l'ordre, sur [[B]] pour les mesures B, sur [[A]] + [[B]] pour les mesures A puis les mesures B.",
        "Pendant la lecture, les pads de pas montrent la mesure entendue. Maintenez [[A]] ou [[B]] pour voir les mesures de ce côté : la mesure jouée clignote en jaune.",
        "Changez de pattern : chaque pattern a ses propres mesures et longueurs.",
      ],
      gestures: [
        ["[[A]] + pad 1–8", "Choisit la mesure n sur ses pas A. Le côté A fait au moins n mesures ({{  An}})"],
        ["[[B]] + pad 1–8", "Pareil sur les pas B ({{  Bn}})"],
        ["[[A]] ou [[B]] + [[CLEAR]] + pad n", "Ce côté fait exactement n mesures : pour raccourcir"],
        ["[[A]] + [[B]] + pad n", "Les deux côtés font n mesures ({{AB n}})"],
        ["[[A]] + [[B]] + [[CLEAR]] + un pad", "Les deux côtés reviennent au pattern normal ({{AB--}})"],
      ],
      notes: [
        "Une mesure jamais enregistrée joue le pattern lui-même : un pattern sonne comme avant tant que vous ne modifiez pas de mesure.",
        "Choisir une mesure est aussi un saut : en lecture, elle joue à la prochaine fin de mesure ; à l'arrêt, le prochain départ commence par elle.",
        "Raccourcir un côté n'efface pas ses mesures : rallongez-le pour les retrouver.",
        "Les pads 9 à 16 restent des pads de pas normaux, et [[LAST STEP]] + pad garde ses fonctions normale et polyrythme.",
        "Les mesures sont sauvegardées dans la mémoire flash de la TR-8 et survivent à l'extinction. Une mise à jour Roland, ou l'installation du fichier officiel, les efface.",
        "Si l'écran affiche {{FAIL}}, une mesure n'a pas été sauvegardée : éteignez et rallumez la TR-8, puis vérifiez la mesure.",
      ],
    },
  },
};
