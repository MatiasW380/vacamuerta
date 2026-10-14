/* Página del estudio, en portugués y griego */
window.AIM_TR = window.AIM_TR || {};
window.AIM_TR.estudio = {
  pt: {
    crumbHere: "Serviços jurídicos", kicker: "Escritório de advocacia · Córdoba, Argentina",
    h1: "Onassis & Baronetto. Advogados para empresas e investidores na Argentina.",
    heritage: "Com raízes na Grécia e em Córdoba, o escritório une uma tradição ligada aos negócios internacionais ao conhecimento do direito argentino. Tradição e atualidade unidas para agregar valor aos nossos clientes e segurança jurídica aos seus investimentos.",
    lede: "Acompanhamos empresas e investidores, locais e estrangeiros, em cada etapa de um investimento na Argentina: da estrutura com que chegam ao país aos seus contratos, licenças e à regulação do seu setor.",
    ctaWrite: "Escrever ao escritório", ctaAreas: "Áreas de atuação", areasTitle: "Áreas de atuação",
    howTitle: "Como trabalhamos",
    steps: [
      ["Primeira conversa", "Você nos conta o projeto e em que etapa está. Dizemos o que é necessário e em que ordem."],
      ["Proposta por escrito", "Antes de começar, enviamos por escrito o escopo do trabalho e seus prazos."],
      ["Acompanhamento completo", "Seguimos o projeto do início ao fim, com os dados do monitor como referência para cada setor."],
    ],
    monitorNote: "O Argentina Invest Monitor é a ferramenta pública do escritório: reúne os dados oficiais que acompanhamos para assessorar nossos clientes, setor por setor.",
    contactTitle: "Contato", contactText: "Conte-nos brevemente sobre o seu projeto e responderemos.", contactMail: "E-mail",
    fName: "Nome", fCompany: "Empresa", fEmail: "E-mail", fMsg: "Seu projeto", fSend: "Preparar o e-mail", fHint: "Seu programa de e-mail abre com a mensagem pronta para enviar.",
    errName: "Escreva seu nome.", errEmail: "Digite um e-mail válido.", errMsg: "Conte-nos brevemente sobre o seu projeto.",
    subject: (n, c) => `Consulta pelo Argentina Invest Monitor: ${n}${c ? " (" + c + ")" : ""}`,
    body: (n, c, e, m) => `Nome: ${n}\nEmpresa: ${c || "-"}\nE-mail: ${e}\n\n${m}`,
    fine: "As informações deste site são gerais e não constituem assessoria jurídica para um caso concreto. A relação profissional começa somente quando o escritório aceita o trabalho por escrito.",
  },
  el: {
    crumbHere: "Νομικές υπηρεσίες", kicker: "Δικηγορικό γραφείο · Córdoba, Αργεντινή",
    h1: "Onassis & Baronetto. Δικηγόροι για εταιρείες και επενδυτές στην Αργεντινή.",
    heritage: "Με ρίζες στην Ελλάδα και στην Κόρδοβα, το γραφείο συνδυάζει μια παράδοση συνδεδεμένη με τις διεθνείς επιχειρήσεις με τη γνώση του αργεντίνικου δικαίου. Παράδοση και σύγχρονη πραγματικότητα μαζί, για να προσθέτουμε αξία στους πελάτες μας και ασφάλεια δικαίου στις επενδύσεις τους.",
    lede: "Συνοδεύουμε εταιρείες και επενδυτές, εγχώριους και από το εξωτερικό, σε κάθε βήμα μιας επένδυσης στην Αργεντινή: από τη δομή με την οποία εισέρχονται στη χώρα έως τις συμβάσεις, τις άδειες και το ρυθμιστικό πλαίσιο του τομέα τους.",
    ctaWrite: "Γράψτε στο γραφείο", ctaAreas: "Τομείς πρακτικής", areasTitle: "Τομείς πρακτικής",
    howTitle: "Πώς εργαζόμαστε",
    steps: [
      ["Πρώτη συζήτηση", "Μας περιγράφετε το έργο και σε ποιο στάδιο βρίσκεται. Σας λέμε τι χρειάζεται και με ποια σειρά."],
      ["Γραπτή πρόταση", "Πριν ξεκινήσουμε, σας στέλνουμε γραπτώς το αντικείμενο της εργασίας και το χρονοδιάγραμμά της."],
      ["Ολοκληρωμένη υποστήριξη", "Παρακολουθούμε το έργο από την αρχή έως το τέλος, με τα δεδομένα του monitor ως σημείο αναφοράς για κάθε τομέα."],
    ],
    monitorNote: "Το Argentina Invest Monitor είναι το δημόσιο εργαλείο του γραφείου: συγκεντρώνει τα επίσημα στοιχεία που παρακολουθούμε για να συμβουλεύουμε τους πελάτες μας, τομέα προς τομέα.",
    contactTitle: "Επικοινωνία", contactText: "Περιγράψτε μας σύντομα το έργο σας και θα σας απαντήσουμε.", contactMail: "Email",
    fName: "Όνομα", fCompany: "Εταιρεία", fEmail: "Email", fMsg: "Το έργο σας", fSend: "Προετοιμασία email", fHint: "Ανοίγει το πρόγραμμα email σας με το μήνυμα έτοιμο για αποστολή.",
    errName: "Γράψτε το όνομά σας.", errEmail: "Γράψτε ένα έγκυρο email.", errMsg: "Περιγράψτε μας σύντομα το έργο σας.",
    subject: (n, c) => `Ερώτημα από το Argentina Invest Monitor: ${n}${c ? " (" + c + ")" : ""}`,
    body: (n, c, e, m) => `Όνομα: ${n}\nΕταιρεία: ${c || "-"}\nEmail: ${e}\n\n${m}`,
    fine: "Οι πληροφορίες του ιστότοπου είναι γενικές και δεν αποτελούν νομική συμβουλή για συγκεκριμένη υπόθεση. Η επαγγελματική σχέση ξεκινά μόνο όταν το γραφείο αποδεχθεί γραπτώς την ανάθεση.",
  },
};
