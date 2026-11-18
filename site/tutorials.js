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
        "Hold [[LAST STEP]] + [[CH]] to see its length: the steps inside it are green.",
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
        "Weak notes of the instrument follow its loop. The global accent (AC) follows the pattern.",
        "Each instrument goes back to its step 1 when you start or stop.",
        "Scatter works on top of the lengths: each instrument keeps its own loop.",
        "In TR-REC, [[LAST STEP]] blinks while the selected instrument has its own length, and the step cursor loops over its steps 1 to L.",
      ],
    },
    fr: {
      tab: "Polyrythme",
      intro: "Donnez à un instrument sa propre longueur de boucle. Un instrument de longueur L joue ses pas 1 à L en boucle, contre la longueur du pattern.",
      steps: [
        "Sur un pattern de 16 pas, placez le charleston fermé [[CH]] sur le pas 1 seulement.",
        "Maintenez [[LAST STEP]] et [[CH]], puis appuyez sur le pad [[3]]. L'écran affiche {{L  3}}.",
        "Lancez le pattern : [[CH]] joue tous les trois pas, 3 contre 16.",
        "Maintenez [[LAST STEP]] + [[CH]] pour voir sa longueur : les pas compris sont verts.",
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
        "Les notes faibles de l'instrument suivent sa boucle. L'accent global (AC) suit le pattern.",
        "Chaque instrument revient à son pas 1 au départ et à l'arrêt.",
        "Le scatter s'applique par-dessus les longueurs : chaque instrument garde sa boucle.",
        "En TR-REC, [[LAST STEP]] clignote quand l'instrument sélectionné a sa propre longueur, et le curseur des pas boucle sur ses pas 1 à L.",
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
        "Press [[A]] to play the A bars in order, [[B]] for the B bars. Hold [[A]] and press [[B]] (or the reverse) for A+B. In [[INST PLAY]] the side that plays is lit and the other one blinks; in [[TR-REC]] the lit side is the side you edit (hold [[B]] and press [[A]] to edit A, the reverse to edit B). With bars, A+B plays all the A bars and then all the B bars; without bars it alternates A and B at each pass, as in stock. A side with no bars is skipped: with only an A sequence, A+B plays only the A bars.",
        "While it plays, the display shows the bar you hear and the number of bars of its side ({{A1-4}}: bar 1 of 4) and the step pads show its steps. Hold [[A]] or [[B]] to see that side's bars: the bar that plays is yellow. A side with no bars shows pad 1 in green.",
        "Change pattern: each pattern has its own bars and lengths.",
      ],
      gestures: [
        ["[[A]] + pad 1–8", "Select bar n on its A steps. Side A becomes at least n bars ({{  An}})"],
        ["[[B]] + pad 1–8", "The same on the B steps ({{  Bn}})"],
        ["[[A]] or [[B]] + [[CLEAR]] + pad n", "That side becomes exactly n bars: use it to shorten"],
        ["[[A]] + [[B]] + pad n", "Both sides n bars ({{AB n}})"],
        ["[[A]] + [[B]] + [[CLEAR]] + any pad", "Both sides back to the normal pattern ({{AB--}})"],
        ["[[A]] or [[B]] + tap [[LAST STEP]]", "Expand that side: one bar shorter than 16 steps doubles its steps ({{A  8}}, {{A 16}}), otherwise the bars double ({{A b2}}, {{A b4}}, {{A b8}})"],
        ["[[A]] + [[B]] + tap [[LAST STEP]]", "Copy A to B: B gets the steps and the length of A ({{AB n}})"],
      ],
      notes: [
        "A bar you never recorded plays the pattern itself, so a pattern sounds as before until you edit a bar.",
        "Selecting a bar is also a jump: while playing, it plays at the next bar boundary; stopped, the next start begins there.",
        "Shortening a side does not erase its bars: make the side longer again to get them back.",
        "Pads 9 to 16 stay normal step pads, and [[LAST STEP]] + pad keeps its normal and polyrhythm functions.",
        "Expand copies the side after its end: 4 steps become 8, then 16, then 2, 4 and 8 bars. 3 bars become 6. A side of 8 bars shows {{FULL}}. Only the side you hold changes. If you press a pad before you release [[LAST STEP]], nothing is expanded and the pad works as before.",
        "The bars are saved in the flash of the TR-8 and survive power off and installing another firmware built here. A Roland firmware update, or installing the official file, erases them. The USB backup does not contain them.",
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
        "Appuyez sur [[A]] pour jouer les mesures A dans l'ordre, sur [[B]] pour les mesures B. Maintenez [[A]] et appuyez sur [[B]] (ou l'inverse) pour A+B. En [[INST PLAY]], le côté qui joue est allumé et l'autre clignote ; en [[TR-REC]], le côté allumé est celui que vous éditez (maintenez [[B]] et appuyez sur [[A]] pour éditer A, l'inverse pour éditer B). Avec des mesures, A+B joue toutes les mesures A puis toutes les mesures B ; sans mesures, il alterne A et B à chaque tour, comme d'origine. Un côté sans mesures est sauté : avec seulement une séquence A, A+B ne joue que les mesures A.",
        "Pendant la lecture, l'écran affiche la mesure entendue et le nombre de mesures de son côté ({{A1-4}} : mesure 1 sur 4) et les pads de pas montrent ses pas. Maintenez [[A]] ou [[B]] pour voir les mesures de ce côté : la mesure jouée est en jaune. Un côté sans mesures affiche le pad 1 en vert.",
        "Changez de pattern : chaque pattern a ses propres mesures et longueurs.",
      ],
      gestures: [
        ["[[A]] + pad 1–8", "Choisit la mesure n sur ses pas A. Le côté A fait au moins n mesures ({{  An}})"],
        ["[[B]] + pad 1–8", "Pareil sur les pas B ({{  Bn}})"],
        ["[[A]] ou [[B]] + [[CLEAR]] + pad n", "Ce côté fait exactement n mesures : pour raccourcir"],
        ["[[A]] + [[B]] + pad n", "Les deux côtés font n mesures ({{AB n}})"],
        ["[[A]] + [[B]] + [[CLEAR]] + un pad", "Les deux côtés reviennent au pattern normal ({{AB--}})"],
        ["[[A]] ou [[B]] + appui bref sur [[LAST STEP]]", "Double ce côté : une mesure de moins de 16 pas double ses pas ({{A  8}}, {{A 16}}), sinon les mesures doublent ({{A b2}}, {{A b4}}, {{A b8}})"],
        ["[[A]] + [[B]] + appui bref sur [[LAST STEP]]", "Copie A vers B : B prend les pas et la longueur de A ({{AB n}})"],
      ],
      notes: [
        "Une mesure jamais enregistrée joue le pattern lui-même : un pattern sonne comme avant tant que vous ne modifiez pas de mesure.",
        "Choisir une mesure est aussi un saut : en lecture, elle joue à la prochaine fin de mesure ; à l'arrêt, le prochain départ commence par elle.",
        "Raccourcir un côté n'efface pas ses mesures : rallongez-le pour les retrouver.",
        "Les pads 9 à 16 restent des pads de pas normaux, et [[LAST STEP]] + pad garde ses fonctions normale et polyrythme.",
        "Le doublement copie le côté après sa fin : 4 pas deviennent 8, puis 16, puis 2, 4 et 8 mesures. 3 mesures deviennent 6. Un côté de 8 mesures affiche {{FULL}}. Seul le côté maintenu change. Si vous appuyez sur un pad avant de relâcher [[LAST STEP]], rien n'est doublé et le pad fonctionne comme avant.",
        "Les mesures sont sauvegardées dans la mémoire flash de la TR-8 et survivent à l'extinction et à l'installation d'un autre firmware construit ici. Une mise à jour Roland, ou l'installation du fichier officiel, les efface. La sauvegarde USB ne les contient pas.",
        "Si l'écran affiche {{FAIL}}, une mesure n'a pas été sauvegardée : éteignez et rallumez la TR-8, puis vérifiez la mesure.",
      ],
    },
  },
};
