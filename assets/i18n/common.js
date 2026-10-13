/* Textos compartidos en portugués y griego: pie de página y suscripción.
   Cada página completa T.pt y T.el con: inglés de base + estos textos + los de la página. */
window.AIM_TR = window.AIM_TR || {};
window.AIM_LANGS = ["en", "es", "pt", "el"];
window.AIM_LOCALE = { en: "en-US", es: "es-AR", pt: "pt-BR", el: "el-GR" };
window.AIM_TV_LOCALE = { en: "en", es: "es", pt: "br", el: "en" };
window.AIM_PICK_LANG = function (saved) {
  if (window.AIM_LANGS.includes(saved)) return saved;
  const n = (navigator.language || "").toLowerCase().slice(0, 2);
  return window.AIM_LANGS.includes(n) ? n : "en";
};
window.AIM_EXTEND = function (T, page) {
  const tr = window.AIM_TR;
  ["pt", "el"].forEach(l => {
    T[l] = Object.assign({}, T.en, (tr.common || {})[l], ((tr[page] || {})[l]) || {});
  });
  return T;
};
window.AIM_TR.common = {
  pt: {
    emailPh: "voce@empresa.com",
    signupTitle: "A semana dos investimentos na Argentina, em cinco minutos",
    signupText: "Um e-mail curto por semana com os números que se moveram, as novas aprovações do RIGI e as normas que importam para quem investe.",
    emailLabel: "E-mail", subscribe: "Inscrever-se", sending: "Inscrevendo…",
    ok: "Pronto, você está inscrito. O primeiro envio chega na próxima semana.",
    badEmail: "Digite um e-mail válido, como nome@empresa.com.",
    notReady: "As inscrições abrem em breve. Tente novamente em alguns dias.",
    fail: "A inscrição não foi concluída. Tente novamente em um minuto.",
    footSources: "Todos os números vêm de fontes públicas e oficiais, citadas em cada página.",
    fAbout: "Os dados públicos oficiais da Argentina sobre energia, mineração, agro, finanças e indústria, organizados para investidores e atualizados automaticamente.",
    fSectors: "Setores", fEnergy: "Energia: Vaca Muerta", fMining: "Mineração", fAgro: "Agro", fFinance: "Finanças e bancos", fIndustry: "Indústria",
    fResources: "Recursos", fMethod: "Metodologia e fontes", fCsv: "Baixar dados de Vaca Muerta (CSV)", fNewsletter: "Newsletter semanal",
    disclaimer: "Informação para fins informativos. Não constitui recomendação de investimento.",
    topicNames: { Hidrocarburos: "Hidrocarbonetos", "Gas natural": "Gás natural", "Petróleo": "Petróleo", Biocombustibles: "Biocombustíveis" },
  },
  el: {
    emailPh: "esy@etaireia.com",
    signupTitle: "Η εβδομάδα των επενδύσεων στην Αργεντινή, σε πέντε λεπτά",
    signupText: "Ένα σύντομο εβδομαδιαίο email με τα μεγέθη που κινήθηκαν, τις νέες εγκρίσεις RIGI και τους κανονισμούς που μετρούν για τους επενδυτές.",
    emailLabel: "Διεύθυνση email", subscribe: "Εγγραφή", sending: "Γίνεται εγγραφή…",
    ok: "Η εγγραφή ολοκληρώθηκε. Το πρώτο τεύχος έρχεται την επόμενη εβδομάδα.",
    badEmail: "Γράψτε ένα έγκυρο email, π.χ. onoma@etaireia.com.",
    notReady: "Οι εγγραφές ανοίγουν σύντομα. Δοκιμάστε ξανά σε λίγες ημέρες.",
    fail: "Η εγγραφή δεν ολοκληρώθηκε. Δοκιμάστε ξανά σε ένα λεπτό.",
    footSources: "Όλα τα στοιχεία προέρχονται από δημόσιες, επίσημες πηγές που αναφέρονται σε κάθε σελίδα.",
    fAbout: "Τα επίσημα δημόσια στοιχεία της Αργεντινής για την ενέργεια, την εξόρυξη, τη γεωργία, τα χρηματοοικονομικά και τη βιομηχανία, οργανωμένα για επενδυτές και ενημερωμένα αυτόματα.",
    fSectors: "Τομείς", fEnergy: "Ενέργεια: Vaca Muerta", fMining: "Εξόρυξη", fAgro: "Γεωργία", fFinance: "Χρηματοοικονομικά και τράπεζες", fIndustry: "Βιομηχανία",
    fResources: "Πόροι", fMethod: "Μεθοδολογία και πηγές", fCsv: "Λήψη δεδομένων Vaca Muerta (CSV)", fNewsletter: "Εβδομαδιαίο ενημερωτικό δελτίο",
    disclaimer: "Μόνο για ενημέρωση. Δεν αποτελεί επενδυτική συμβουλή.",
    topicNames: { Hidrocarburos: "Υδρογονάνθρακες", "Gas natural": "Φυσικό αέριο", "Petróleo": "Πετρέλαιο", Biocombustibles: "Βιοκαύσιμα" },
  },
};
