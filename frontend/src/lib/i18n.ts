import { useCallback, useEffect, useState } from "react";

export type Lang = "tr" | "en";

const LS_KEY = "aws.lang";

type Dict = Record<string, string>;

const tr: Dict = {
  "app.title": "Advanced Web Search",
  "app.tagline": "Derin Araştırma",
  "nav.home": "Ana Sayfa",
  "nav.settings": "Ayarlar",
  "nav.about": "Proje Yapısı",
  "nav.research": "Araştırma",

  "home.heroTitle": "Popülerlik değil, kanıt.",
  "home.heroSub":
    "Advanced Web Search; güncel, doğrulanmış ve yüksek kaliteli kaynakları çoklu-ajan mimarisiyle tarar. Arama motorlarının popülerlik sıralamasını aşar.",
  "home.queryLabel": "Araştırma sorunuz",
  "home.queryPlaceholder":
    "Örn. GLP-1 ilaçlarının uzun vadeli kardiyovasküler etkileri nelerdir?",
  "home.language": "Dil",
  "home.lang.auto": "Otomatik",
  "home.lang.tr": "Türkçe",
  "home.lang.en": "İngilizce",
  "lang.auto": "Otomatik",
  "lang.tr": "Türkçe",
  "lang.en": "İngilizce",
  "lang.es": "İspanyolca",
  "lang.fr": "Fransızca",
  "lang.de": "Almanca",
  "lang.ar": "Arapça",
  "lang.ru": "Rusça",
  "lang.zh": "Çince",
  "home.reportLanguage": "Rapor dili",
  "home.reportLanguageHint":
    "Bir veya birden fazla dil seçin. Her dil ayrı ve paralel üretilir.",
  "home.requireApproval": "Plan onayı iste",
  "home.requireApprovalHint":
    "Araştırma başlamadan önce alt-soruları düzenleyip onaylayın.",
  "home.depth": "Arama derinliği",
  "depth.quick": "Hızlı",
  "depth.standard": "Standart",
  "depth.deep": "Derin",
  "depth.exhaustive": "Kapsamlı",
  "depth.quick.desc": "4 alt-konu, tek tur, hızlı tarama",
  "depth.standard.desc": "8 alt-konu, çok-turlu, dengeli",
  "depth.deep.desc": "12 alt-konu, çok-turlu, atıf snowballing, çift-dilli",
  "depth.exhaustive.desc":
    "16+ alt-konu, derin özyineleme, agresif snowballing, çift-dilli",
  "home.submit": "Araştır",
  "home.submitting": "Başlatılıyor…",
  "home.recent": "Son projeler",
  "home.noProjects": "Henüz proje yok. İlk araştırmanızı başlatın.",
  "home.value1": "Doğrulanmış iddialar",
  "home.value1d": "Her iddia, çapraz kaynaklarla adversaryal biçimde doğrulanır.",
  "home.value2": "Güncel kaynaklar",
  "home.value2d": "Akademik, ön-baskı ve web kaynaklarını tazelik için sıralar.",
  "home.value3": "Yüksek kalite",
  "home.value3d": "Otorite, kanıt türü ve atıf etkisine göre puanlanır.",

  "banner.noModel":
    "Araştırma için bir model gerekli — Ollama kurun ya da Ayarlar'dan bir API anahtarı ekleyin.",
  "banner.noModel.link": "Ayarlar'a git",
  "banner.dismiss": "Kapat",

  "run.error": "Çalıştırma hatası",
  "run.cancel": "Durdur",
  "run.cancelling": "Durduruluyor…",
  "run.cancelled": "Durduruldu",

  "research.status": "Durum",
  "research.trace": "Ajan İzi",
  "research.graph": "Konu Grafiği",
  "research.report": "Rapor",
  "research.trailTab": "Araştırma İzi",
  "research.sources": "Kaynaklar",
  "research.approval": "Plan Onayı",
  "research.cancel": "İptal",
  "research.cancelled": "İptal edildi",
  "research.waitingStart": "Araştırma başlatılıyor…",
  "research.connecting": "Bağlanıyor…",
  "research.noReport": "Rapor henüz hazır değil.",
  "research.streaming": "Rapor yazılıyor…",
  "research.notFound": "Proje bulunamadı.",
  "research.back": "Geri",
  "research.console": "Konsol",

  "terminal.title": "advanced-web-search@deep-search — canlı",
  "terminal.clear": "Temizle",
  "terminal.copy": "Tümünü kopyala",
  "terminal.autoscroll": "Otomatik kaydır",
  "terminal.jumpToBottom": "En alta git",
  "terminal.earlierLines": "önceki satır",

  "approval.title": "Alt-soruları onaylayın",
  "approval.hint":
    "Soruları düzenleyin, perspektif ekleyin, gereksizleri kapatın veya yeni soru ekleyin.",
  "approval.question": "Soru",
  "approval.perspective": "Perspektif",
  "approval.perspectivePlaceholder": "ör. eleştirel, ekonomik…",
  "approval.keep": "Dahil et",
  "approval.add": "Soru ekle",
  "approval.extra": "Ek talimatlar",
  "approval.extraPlaceholder":
    "Araştırmacıya ek yönlendirme (ops.)…",
  "approval.submit": "Onayla ve araştır",
  "approval.submitting": "Gönderiliyor…",

  "trace.waiting": "Olay bekleniyor…",
  "trace.active": "çalışıyor",

  "node.planner": "Planlayıcı",
  "node.moderator": "Moderatör",
  "node.approval": "Onay",
  "node.researcher": "Araştırmacı",
  "node.ranker": "Sıralayıcı",
  "node.synthesizer": "Sentezleyici",
  "node.verifier": "Doğrulayıcı",
  "node.finalizer": "Sonuçlandırıcı",

  "source.kept": "Tutuldu",
  "source.dropped": "Elendi",
  "source.keptOnly": "Sadece tutulanlar",
  "source.cited": "Atıflı",
  "source.citedOnly": "Sadece atıflılar",
  "source.citedShort": "atıflı",
  "source.citedTip": "Bu kaynağa raporda atıf yapıldı",
  "source.all": "Tümü",
  "source.kind": "Tür",
  "source.kind.all": "Tüm türler",
  "source.citedBy": "atıf",
  "source.oa": "Açık Erişim",
  "source.whyKept": "Neden tutuldu",
  "source.noSources": "Henüz kaynak yok.",
  "source.col.title": "Başlık",
  "source.col.kind": "Tür",
  "source.col.relevance": "İlgi",
  "source.col.authority": "Otorite",
  "source.col.recency": "Güncellik",
  "source.col.citation": "Atıf",
  "source.col.evidence": "Kanıt",
  "source.col.match": "Eşleşme",
  "source.col.kept": "Durum",
  "source.expand": "Detay",

  "diversity.title": "Çeşitlilik",
  "diversity.domains": "alan",
  "diversity.sources": "kaynak",
  "diversity.top": "en çok",
  "diversity.echo": "Eko-oda riski",
  "diversity.echoFrom": "tek alandan:",
  "diversity.other": "diğer",

  "verify.legend": "Atıf doğrulama",
  "verify.supported": "Doğrulandı",
  "verify.partial": "Kısmen destekli",
  "verify.unsupported": "Desteklenmiyor",
  "verify.unverifiable": "Doğrulanamaz",

  "trail.queries": "Sorgular",
  "trail.found": "bulundu",
  "trail.kept": "tutuldu",
  "trail.hits": "sonuç",
  "trail.round": "T",
  "trail.dropped": "elenen",
  "trail.other": "Genel / Snowball",
  "trail.empty": "Henüz arama sorgusu yok.",

  "report.consensus": "Uzlaşı Özeti",
  "report.disagreements": "Anlaşmazlıklar",
  "report.comprehensiveness": "Kapsamlılık",
  "report.certainty": "Kesinlik",
  "report.grounding": "Kanıt temeli",
  "report.grounded": "iddia kaynaklı",
  "report.language": "Dil",

  "ask.title": "Rapora sor",
  "ask.placeholder": "Bu çalışmanın kaynaklarına dayalı bir soru sorun…",
  "ask.send": "Sor",
  "ask.notFound": "Bu çalışmanın kaynaklarında ilgili bir bilgi bulunamadı.",
  "ask.ungrounded": "Yanıt kaynaklarla gerekçelendirilemedi.",
  "ask.error": "Soru yanıtlanamadı.",

  "export.title": "Dışa Aktar",
  "export.menu": "Dışa Aktar",
  "export.pdf": "PDF",
  "export.pdf.hint": "Tarayıcıdan PDF olarak kaydet",
  "export.markdown": "Markdown (.md)",
  "export.bibtex": "BibTeX (.bib)",
  "export.ris": "RIS (.ris)",
  "export.csl": "CSL-JSON (.json)",
  "export.html": "HTML",
  "export.language": "Rapor dili",
  "source.copyCite": "Atıfı kopyala",
  "common.copied": "Kopyalandı",

  "settings.title": "Ayarlar",
  "settings.models": "Model Atamaları",
  "settings.modelsHint": "Her ajan rolü için bir model id'si yazın. OpenRouter için 'openrouter/' önekini kullanın (ör. openrouter/deepseek/deepseek-chat). Değişikliğin geçerli olması için Kaydet'e basın.",
  "settings.role.planner": "Planlayıcı",
  "settings.role.moderator": "Moderatör",
  "settings.role.synthesizer": "Sentezleyici",
  "settings.role.verifier": "Doğrulayıcı",
  "settings.weights": "Puanlama Ağırlıkları",
  "settings.weightsHint": "Toplam otomatik olarak 1'e normalize edilir.",
  "settings.requireApproval": "Plan onayı iste",
  "settings.useLocalLlm": "Yerel LLM (Ollama) kullan",
  "settings.useLocalLlmHint":
    "Yerel Ollama taranmaz/kullanılmaz; yalnızca bulut anahtarları kullanılır.",
  "settings.keepThreshold": "Tutma eşiği",
  "settings.maxSubtopics": "Maks. alt-soru",
  "settings.resultsPerSource": "Kaynak başına sonuç",
  "settings.comprehensiveness": "Arama derinliği / Kapsam",
  "settings.comprehensivenessHint":
    "Bir ön ayar seçin veya ince ayar değerlerini elle düzenleyin.",
  "settings.depth": "Derinlik ön ayarı",
  "settings.maxResearchRounds": "Maks. araştırma turu",
  "settings.gapMinSources": "Boşluk için min. kaynak",
  "settings.queryVariants": "Sorgu varyantları",
  "settings.snowballTopK": "Snowball üst-K",
  "settings.presetImplies": "Ön ayar değerleri",
  "settings.preset.subtopics": "alt-konu",
  "settings.preset.rounds": "tur",
  "settings.preset.snowball": "snowball",
  "settings.preset.bilingual": "çift-dilli",
  "settings.preset.recursion": "özyineleme",
  "settings.hardware": "Donanım",
  "settings.recommended": "Önerilen yerel model",
  "settings.totalRam": "Toplam RAM",
  "settings.availableRam": "Kullanılabilir RAM",
  "settings.cpu": "CPU çekirdeği",
  "settings.localOptions": "Yerel model seçenekleri",
  "settings.fits": "Uygun",
  "settings.tooBig": "Yetersiz RAM",
  "settings.providers": "Sağlayıcılar",
  "settings.requiresKey": "Anahtar gerekli",
  "settings.available": "Hazır",
  "settings.unavailable": "Kapalı",
  "settings.save": "Kaydet",
  "settings.saving": "Kaydediliyor…",
  "settings.saved": "Kaydedildi",
  "settings.custom": "Özel…",
  "settings.none": "(yok)",
  "settings.testConnection": "Bağlantıyı test et",
  "settings.testing": "Test ediliyor…",
  "settings.testOk": "Bağlantı başarılı",
  "settings.testFailed": "Bağlantı başarısız",

  "settings.provSection": "AI Modelleri & Sağlayıcılar",
  "settings.provSectionHint":
    "Bulut anahtarları, yerel modeller ve kendi sunucun. API anahtarları şifreli kasada saklanır ve repoya gitmez.",
  "settings.statusLabel": "Durum",
  "settings.modeNone": "Yapılandırılmamış",
  "settings.activeBackend": "Aramalarda hangi AI kullanılsın?",
  "settings.backendAuto": "Otomatik (anahtar varsa bulut, yoksa yerel)",
  "settings.backendCloud": "Bulut sağlayıcı",
  "settings.backendOllama": "Kendi bilgisayarım (Ollama)",
  "settings.backendCustom": "Kendi sunucum (OpenAI-uyumlu)",
  "settings.applyConnection": "Bağlantı ayarlarını kaydet",
  "settings.applied": "Kaydedildi",

  "settings.vault": "Şifreli kasa",
  "settings.vaultSetupHint":
    "Bulut API anahtarlarını şifreli saklamak için bir ana parola belirle. Parola hiçbir yere kaydedilmez; her açılışta kilidi açman gerekir.",
  "settings.vaultMasterPassword": "Ana parola",
  "settings.vaultConfirmPassword": "Ana parola (tekrar)",
  "settings.vaultSetBtn": "Kasayı oluştur",
  "settings.vaultLocked": "Kasa kilitli",
  "settings.vaultLockedHint": "Saklı anahtarları kullanmak için ana parolayı gir.",
  "settings.vaultUnlock": "Kilidi aç",
  "settings.vaultUnlocking": "Açılıyor…",
  "settings.vaultLock": "Kilitle",
  "settings.vaultUnlocked": "Kasa açık",
  "settings.vaultWrongPassword": "Ana parola yanlış",
  "settings.vaultChangePassword": "Parolayı değiştir",
  "settings.vaultOldPassword": "Eski parola",
  "settings.vaultNewPassword": "Yeni parola",
  "settings.vaultReset": "Kasayı sıfırla",
  "settings.vaultResetConfirm":
    "Tüm saklı API anahtarları kalıcı olarak silinecek. Emin misin?",
  "settings.vaultPasswordMismatch": "Parolalar eşleşmiyor",
  "settings.vaultPasswordShort": "Parola en az 8 karakter olmalı",

  "settings.cloudProviders": "Bulut sağlayıcılar",
  "settings.cloudProvidersHint":
    "Bir API anahtarı yapıştır ve Doğrula'ya bas. Doğrulanan anahtar şifreli kasaya kaydedilir.",
  "settings.unlockToManage": "Anahtarları girmek için önce kasanın kilidini aç.",
  "settings.apiKeyPlaceholder": "API anahtarını yapıştır",
  "settings.verify": "Doğrula",
  "settings.verifying": "Doğrulanıyor…",
  "settings.valid": "Geçerli",
  "settings.invalid": "Geçersiz",
  "settings.stored": "Kayıtlı",
  "settings.keyFromEnv": ".env'den",
  "settings.change": "Değiştir",
  "settings.activeProviderLabel": "Aktif sağlayıcı",

  "settings.localOllama": "Kendi bilgisayarım (Ollama)",
  "settings.ollamaUrl": "Ollama adresi",
  "settings.connect": "Bağlan",
  "settings.connected": "Bağlandı",
  "settings.modelsFound": "model bulundu",
  "settings.notConnected": "Bağlanılamadı",
  "settings.localModelLabel": "Model",
  "settings.autoBySize": "Otomatik (RAM'e göre)",

  "settings.customServer": "Kendi sunucum (OpenAI-uyumlu)",
  "settings.customServerHint": "LM Studio · llama.cpp · vLLM · TGI",
  "settings.serverUrl": "Sunucu adresi",
  "settings.modelName": "Model adı",
  "settings.apiKeyOptional": "API anahtarı (varsa)",

  "settings.roles": "Ajan rolleri",
  "settings.rolesHint":
    "Her rolü farklı bir backend'e atayabilirsin (bulut · yerel Ollama · kendi sunucun). Boş bırakırsan o rol aktif varsayılanı kullanır.",
  "settings.role.default": "(varsayılan)",

  "weights.relevance": "İlgi",
  "weights.authority": "Otorite",
  "weights.recency": "Güncellik",
  "weights.citation_impact": "Atıf etkisi",
  "weights.evidence": "Kanıt",

  "common.loading": "Yükleniyor…",
  "common.error": "Bir hata oluştu",
  "common.retry": "Tekrar dene",
  "common.delete": "Sil",
  "common.open": "Aç",

  "status.queued": "Sırada",
  "status.running": "Çalışıyor",
  "status.awaiting_approval": "Onay bekliyor",
  "status.completed": "Tamamlandı",
  "status.finished": "Tamamlandı",
  "status.error": "Hata",
  "status.cancelled": "İptal",
  "status.idle": "Boşta",

  // ── About / Hakkında ─────────────────────────────────────────────
  "about.title": "Advanced Web Search Nasıl Çalışır?",
  "about.intro":
    "Advanced Web Search, popülerlik sıralı aramanın ötesine geçer: çok-ajanlı bir motorla güncel, doğrulanmış ve yüksek kaliteli kaynakları tarar; her iddiayı kaynaklarla adversaryal biçimde sınar ve şeffaf, atıflı bir rapor üretir. Aşağıdaki akış şemaları, sistemin uçtan uca nasıl işlediğini gösterir.",
  "about.openSource":
    "Advanced Web Search açık kaynaklıdır ve MIT lisansıyla dağıtılır. Katkılar memnuniyetle karşılanır.",

  "about.tab.overview": "Genel Bakış",
  "about.tab.agents": "Çok-Ajan Akışı",
  "about.tab.retrieval": "Retrieval",
  "about.tab.scoring": "Skorlama",
  "about.tab.architecture": "Mimari",
  "about.tab.features": "Özellikler",
  "about.tab.contribute": "Katkıda Bulun",

  "about.lifecycle.title": "İstek Yaşam Döngüsü",
  "about.lifecycle.caption":
    "Bir araştırma isteğinin arayüzden motora ve geri rapora kadar izlediği yol. Canlı olaylar SSE ile akar.",

  "about.agents.title": "Çok-Ajan Akışı",
  "about.agents.caption":
    "Sistemin kalbi: planlama, moderasyon, opsiyonel insan onayı, paralel araştırma, sıralama, gap döngüsü, sentez ve doğrulama.",

  "about.retrieval.title": "Retrieval Boru Hattı",
  "about.retrieval.caption":
    "Her alt-soru için sorgu genişletmeden çok-kaynaklı fan-out'a, hibrit aramaya ve 5-sinyalli skora kadar olan adımlar.",

  "about.scoring.title": "Kaynak Skorlaması",
  "about.scoring.caption":
    "Beş sinyal ağırlıklı olarak birleşip 0–100 arası bir eşleşme skoru üretir; eşik altı kaynaklar elenir.",
  "about.scoring.formula":
    "final = 0.40·İlgi + 0.15·Otorite + 0.15·Güncellik + 0.15·Atıf + 0.15·Kanıt (ağırlıklar Ayarlar'dan değiştirilebilir)",

  "about.architecture.title": "Mimari",
  "about.architecture.caption":
    "React arayüzü, FastAPI + LangGraph backend'i ve tek dosyalık SQLite veritabanı (ilişkisel + sqlite-vec + FTS5).",

  "about.features.title": "Özellikler",
  "about.feat.depth.title": "Derinlik ön ayarları",
  "about.feat.depth.desc": "Hızlı'dan Kapsamlı'ya tek tıkla derinlik seçimi.",
  "about.feat.hitl.title": "HITL plan onayı",
  "about.feat.hitl.desc": "Araştırma başlamadan alt-soruları düzenleyip onaylayın.",
  "about.feat.gap.title": "İteratif gap-döngüsü",
  "about.feat.gap.desc": "Eksik açılar tespit edilince yeni araştırma turu açılır.",
  "about.feat.snowball.title": "Atıf snowballing",
  "about.feat.snowball.desc": "Güçlü kaynakların atıf ağı üzerinden yeni kaynaklar bulunur.",
  "about.feat.bilingual.title": "Çift-dilli arama",
  "about.feat.bilingual.desc": "Sorgular TR↔EN genişletilerek daha geniş kapsam sağlanır.",
  "about.feat.transparent.title": "Şeffaf skorlama",
  "about.feat.transparent.desc":
    "Her kaynağın skoru, 'neden tutuldu' gerekçesi ve raporda atıf alıp almadığı görünür; rapordaki [n] işaretleri tam olarak ilgili kaynağa götürür.",
  "about.feat.verify.title": "Atıf doğrulama",
  "about.feat.verify.desc":
    "Her [n] atfı, kaynağın gerçek metniyle karşılaştırılır (embedding + LLM): destekleniyor / kısmen / desteklenmiyor / doğrulanamaz. Desteklenmeyen iddialar yeniden araştırmaya yönlendirilir; kesinlik puanı kaynakların iddiayı gerçekten desteklediği orana göre hesaplanır.",
  "about.feat.disagreement.title": "Anlaşmazlık tespiti",
  "about.feat.disagreement.desc":
    "Rapor, kaynakların çeliştiği veya belirsiz kaldığı noktaları ayrı bir bölümde açıkça gösterir.",
  "about.feat.diversity.title": "Kaynak çeşitliliği",
  "about.feat.diversity.desc":
    "Alan adı çeşitliliği ölçülür; kanıt tek bir alanda yoğunlaşınca eko-oda uyarısı verilir.",
  "about.feat.trail.title": "Araştırma izi",
  "about.feat.trail.desc":
    "Hangi sorguların atıldığı, kaç sonuç döndüğü ve hangi kaynakların tutulduğu/elendiği şeffafça izlenir.",
  "about.feat.ask.title": "Rapora sor",
  "about.feat.ask.desc":
    "Rapor bittikten sonra, yalnızca o çalışmanın topladığı kaynaklara dayalı takip soruları sorulur; cevaplar aynı [n] atıflarıyla gelir.",
  "about.feat.console.title": "Canlı terminal/konsol",
  "about.feat.console.desc": "Tüm ajan adımları gerçek zamanlı canlı konsolda akar.",
  "about.feat.hybrid.title": "Hibrit LLM",
  "about.feat.hybrid.desc": "Bulut API'leri ile yerel Ollama arasında geçiş yapın.",
  "about.feat.embedding.title": "Yerel çok-dilli embedding",
  "about.feat.embedding.desc": "bge-m3 ile cihaz üzerinde embedding ve reranking.",
  "about.feat.export.title": "Atıf & rapor dışa aktarma",
  "about.feat.export.desc": "BibTeX, RIS, Markdown, CSL-JSON ve yazdırılabilir HTML.",
  "about.feat.multilang.title": "Çoklu-dil rapor",
  "about.feat.multilang.desc":
    "Raporu seçtiğiniz bir veya birden fazla dilde, her biri paralel üretilerek alın.",

  "about.contribute.title": "Katkıda Bulun",
  "about.contribute.intro":
    "Advanced Web Search açık kaynaklı (MIT) bir projedir ve katkılarınızı bekliyoruz. Başlamak için:",
  "about.contribute.stack.title": "Teknoloji yığını",
  "about.contribute.stack.desc":
    "Frontend: React 19, Vite, Tailwind. Backend: Python, FastAPI, LangGraph, LiteLLM, fastembed (bge-m3). Veri: tek dosyalık SQLite + sqlite-vec + FTS5.",
  "about.contribute.layout.title": "Proje yapısı",
  "about.contribute.layout.desc":
    "backend/advanced_web_search/{graph/nodes, sources, retrieval, scoring, llm, api} · frontend/src",
  "about.contribute.dev.title": "Geliştirme ortamı",
  "about.contribute.dev.desc":
    "Geliştirme sunucusunu çalıştırın: python scripts/dev.py",
  "about.contribute.tests.title": "Testler",
  "about.contribute.tests.desc": "Testleri çalıştırın: pytest tests/",
  "about.contribute.ideas.title": "İlk katkı için fikirler",
  "about.contribute.idea1":
    "backend/advanced_web_search/sources/ içinde SourceProvider arayüzünü uygulayarak yeni bir kaynak sağlayıcı ekleyin.",
  "about.contribute.idea2":
    "graph/nodes altında yeni bir ajan düğümü ekleyin veya mevcut bir promptu iyileştirin.",
  "about.contribute.idea3":
    "i18n.ts'e yeni bir arayüz dili ekleyin ya da kaynak skorlamasını geliştirin.",
};

const en: Dict = {
  "app.title": "Advanced Web Search",
  "app.tagline": "Deep Research",
  "nav.home": "Home",
  "nav.settings": "Settings",
  "nav.about": "Project Structure",
  "nav.research": "Research",

  "home.heroTitle": "Evidence, not popularity.",
  "home.heroSub":
    "Advanced Web Search scans current, verified, high-quality sources with a multi-agent architecture. It goes beyond the popularity ranking of search engines.",
  "home.queryLabel": "Your research question",
  "home.queryPlaceholder":
    "e.g. What are the long-term cardiovascular effects of GLP-1 drugs?",
  "home.language": "Language",
  "home.lang.auto": "Auto",
  "home.lang.tr": "Turkish",
  "home.lang.en": "English",
  "lang.auto": "Auto",
  "lang.tr": "Turkish",
  "lang.en": "English",
  "lang.es": "Spanish",
  "lang.fr": "French",
  "lang.de": "German",
  "lang.ar": "Arabic",
  "lang.ru": "Russian",
  "lang.zh": "Chinese",
  "home.reportLanguage": "Report language",
  "home.reportLanguageHint":
    "Pick one or more languages. Each is generated separately, in parallel.",
  "home.requireApproval": "Require plan approval",
  "home.requireApprovalHint":
    "Edit and approve the sub-questions before research starts.",
  "home.depth": "Search depth",
  "depth.quick": "Quick",
  "depth.standard": "Standard",
  "depth.deep": "Deep",
  "depth.exhaustive": "Exhaustive",
  "depth.quick.desc": "4 subtopics, single round, fast scan",
  "depth.standard.desc": "8 subtopics, multi-round, balanced",
  "depth.deep.desc": "12 subtopics, multi-round, citation snowballing, bilingual",
  "depth.exhaustive.desc":
    "16+ subtopics, deep recursion, aggressive snowballing, bilingual",
  "home.submit": "Research",
  "home.submitting": "Starting…",
  "home.recent": "Recent projects",
  "home.noProjects": "No projects yet. Start your first research.",
  "home.value1": "Verified claims",
  "home.value1d": "Every claim is adversarially verified across sources.",
  "home.value2": "Current sources",
  "home.value2d": "Ranks academic, preprint and web sources for freshness.",
  "home.value3": "High quality",
  "home.value3d": "Scored by authority, evidence type and citation impact.",

  "banner.noModel":
    "A model is required for research — install Ollama or add an API key in Settings.",
  "banner.noModel.link": "Go to Settings",
  "banner.dismiss": "Dismiss",

  "run.error": "Run error",
  "run.cancel": "Cancel",
  "run.cancelling": "Cancelling…",
  "run.cancelled": "Cancelled",

  "research.status": "Status",
  "research.trace": "Agent Trace",
  "research.graph": "Topic Graph",
  "research.report": "Report",
  "research.trailTab": "Trail",
  "research.sources": "Sources",
  "research.approval": "Plan Approval",
  "research.cancel": "Cancel",
  "research.cancelled": "Cancelled",
  "research.waitingStart": "Starting research…",
  "research.connecting": "Connecting…",
  "research.noReport": "The report is not ready yet.",
  "research.streaming": "Writing report…",
  "research.notFound": "Project not found.",
  "research.back": "Back",
  "research.console": "Console",

  "terminal.title": "advanced-web-search@deep-search — live",
  "terminal.clear": "Clear",
  "terminal.copy": "Copy all",
  "terminal.autoscroll": "Auto-scroll",
  "terminal.jumpToBottom": "Jump to bottom",
  "terminal.earlierLines": "earlier lines",

  "approval.title": "Approve the sub-questions",
  "approval.hint":
    "Edit questions, add a perspective, drop unneeded ones, or add new questions.",
  "approval.question": "Question",
  "approval.perspective": "Perspective",
  "approval.perspectivePlaceholder": "e.g. critical, economic…",
  "approval.keep": "Include",
  "approval.add": "Add question",
  "approval.extra": "Extra instructions",
  "approval.extraPlaceholder": "Extra guidance for the researcher (opt.)…",
  "approval.submit": "Approve and research",
  "approval.submitting": "Submitting…",

  "trace.waiting": "Waiting for events…",
  "trace.active": "running",

  "node.planner": "Planner",
  "node.moderator": "Moderator",
  "node.approval": "Approval",
  "node.researcher": "Researcher",
  "node.ranker": "Ranker",
  "node.synthesizer": "Synthesizer",
  "node.verifier": "Verifier",
  "node.finalizer": "Finalizer",

  "source.kept": "Kept",
  "source.dropped": "Dropped",
  "source.keptOnly": "Kept only",
  "source.cited": "Cited",
  "source.citedOnly": "Cited only",
  "source.citedShort": "cited",
  "source.citedTip": "This source is cited in the report",
  "source.all": "All",
  "source.kind": "Kind",
  "source.kind.all": "All kinds",
  "source.citedBy": "citations",
  "source.oa": "Open Access",
  "source.whyKept": "Why kept",
  "source.noSources": "No sources yet.",
  "source.col.title": "Title",
  "source.col.kind": "Kind",
  "source.col.relevance": "Rel.",
  "source.col.authority": "Auth.",
  "source.col.recency": "Recency",
  "source.col.citation": "Cit.",
  "source.col.evidence": "Evid.",
  "source.col.match": "Match",
  "source.col.kept": "Status",
  "source.expand": "Details",

  "diversity.title": "Diversity",
  "diversity.domains": "domains",
  "diversity.sources": "sources",
  "diversity.top": "top",
  "diversity.echo": "Echo-chamber risk",
  "diversity.echoFrom": "from one domain:",
  "diversity.other": "other",

  "verify.legend": "Citation check",
  "verify.supported": "Supported",
  "verify.partial": "Partly supported",
  "verify.unsupported": "Unsupported",
  "verify.unverifiable": "Unverifiable",

  "trail.queries": "Queries",
  "trail.found": "found",
  "trail.kept": "kept",
  "trail.hits": "hits",
  "trail.round": "R",
  "trail.dropped": "dropped",
  "trail.other": "General / Snowball",
  "trail.empty": "No search queries yet.",

  "report.consensus": "Consensus Summary",
  "report.disagreements": "Points of Disagreement",
  "report.comprehensiveness": "Comprehensiveness",
  "report.certainty": "Certainty",
  "report.grounding": "Grounding",
  "report.grounded": "claims grounded",
  "report.language": "Language",

  "ask.title": "Ask the report",
  "ask.placeholder": "Ask a question grounded in this run's sources…",
  "ask.send": "Ask",
  "ask.notFound": "Nothing relevant was found in this run's sources.",
  "ask.ungrounded": "The answer could not be grounded in the sources.",
  "ask.error": "Could not answer the question.",

  "export.title": "Export",
  "export.menu": "Export",
  "export.pdf": "PDF",
  "export.pdf.hint": "Save as PDF from your browser",
  "export.markdown": "Markdown (.md)",
  "export.bibtex": "BibTeX (.bib)",
  "export.ris": "RIS (.ris)",
  "export.csl": "CSL-JSON (.json)",
  "export.html": "HTML",
  "export.language": "Report language",
  "source.copyCite": "Copy citation",
  "common.copied": "Copied",

  "settings.title": "Settings",
  "settings.models": "Model Assignments",
  "settings.modelsHint": "Type a model id for each agent role. For OpenRouter use the 'openrouter/' prefix (e.g. openrouter/deepseek/deepseek-chat). Click Save to apply.",
  "settings.role.planner": "Planner",
  "settings.role.moderator": "Moderator",
  "settings.role.synthesizer": "Synthesizer",
  "settings.role.verifier": "Verifier",
  "settings.weights": "Scoring Weights",
  "settings.weightsHint": "The total is automatically normalized to 1.",
  "settings.requireApproval": "Require plan approval",
  "settings.useLocalLlm": "Use local LLM (Ollama)",
  "settings.useLocalLlmHint":
    "Local Ollama is not probed or used; only cloud keys are used.",
  "settings.keepThreshold": "Keep threshold",
  "settings.maxSubtopics": "Max sub-questions",
  "settings.resultsPerSource": "Results per source",
  "settings.comprehensiveness": "Search depth / Comprehensiveness",
  "settings.comprehensivenessHint":
    "Pick a preset or fine-tune the values manually.",
  "settings.depth": "Depth preset",
  "settings.maxResearchRounds": "Max research rounds",
  "settings.gapMinSources": "Min sources per gap",
  "settings.queryVariants": "Query variants",
  "settings.snowballTopK": "Snowball top-K",
  "settings.presetImplies": "Preset values",
  "settings.preset.subtopics": "subtopics",
  "settings.preset.rounds": "rounds",
  "settings.preset.snowball": "snowball",
  "settings.preset.bilingual": "bilingual",
  "settings.preset.recursion": "recursion",
  "settings.hardware": "Hardware",
  "settings.recommended": "Recommended local model",
  "settings.totalRam": "Total RAM",
  "settings.availableRam": "Available RAM",
  "settings.cpu": "CPU cores",
  "settings.localOptions": "Local model options",
  "settings.fits": "Fits",
  "settings.tooBig": "Not enough RAM",
  "settings.providers": "Providers",
  "settings.requiresKey": "Requires key",
  "settings.available": "Ready",
  "settings.unavailable": "Off",
  "settings.save": "Save",
  "settings.saving": "Saving…",
  "settings.saved": "Saved",
  "settings.custom": "Custom…",
  "settings.none": "(none)",
  "settings.testConnection": "Test connection",
  "settings.testing": "Testing…",
  "settings.testOk": "Connection OK",
  "settings.testFailed": "Connection failed",

  "settings.provSection": "AI Models & Providers",
  "settings.provSectionHint":
    "Cloud keys, local models and your own server. API keys are stored in an encrypted vault and never reach the repo.",
  "settings.statusLabel": "Status",
  "settings.modeNone": "Not configured",
  "settings.activeBackend": "Which AI should run your searches?",
  "settings.backendAuto": "Automatic (cloud if a key exists, else local)",
  "settings.backendCloud": "Cloud provider",
  "settings.backendOllama": "My computer (Ollama)",
  "settings.backendCustom": "My own server (OpenAI-compatible)",
  "settings.applyConnection": "Save connection settings",
  "settings.applied": "Saved",

  "settings.vault": "Encrypted vault",
  "settings.vaultSetupHint":
    "Set a master password to store cloud API keys encrypted. The password is never saved; you unlock once per startup.",
  "settings.vaultMasterPassword": "Master password",
  "settings.vaultConfirmPassword": "Master password (again)",
  "settings.vaultSetBtn": "Create vault",
  "settings.vaultLocked": "Vault locked",
  "settings.vaultLockedHint": "Enter the master password to use stored keys.",
  "settings.vaultUnlock": "Unlock",
  "settings.vaultUnlocking": "Unlocking…",
  "settings.vaultLock": "Lock",
  "settings.vaultUnlocked": "Vault unlocked",
  "settings.vaultWrongPassword": "Wrong master password",
  "settings.vaultChangePassword": "Change password",
  "settings.vaultOldPassword": "Old password",
  "settings.vaultNewPassword": "New password",
  "settings.vaultReset": "Reset vault",
  "settings.vaultResetConfirm":
    "All stored API keys will be permanently deleted. Are you sure?",
  "settings.vaultPasswordMismatch": "Passwords do not match",
  "settings.vaultPasswordShort": "Password must be at least 8 characters",

  "settings.cloudProviders": "Cloud providers",
  "settings.cloudProvidersHint":
    "Paste an API key and click Verify. A verified key is stored in the encrypted vault.",
  "settings.unlockToManage": "Unlock the vault first to enter keys.",
  "settings.apiKeyPlaceholder": "Paste API key",
  "settings.verify": "Verify",
  "settings.verifying": "Verifying…",
  "settings.valid": "Valid",
  "settings.invalid": "Invalid",
  "settings.stored": "Stored",
  "settings.keyFromEnv": "from .env",
  "settings.change": "Change",
  "settings.activeProviderLabel": "Active provider",

  "settings.localOllama": "My computer (Ollama)",
  "settings.ollamaUrl": "Ollama address",
  "settings.connect": "Connect",
  "settings.connected": "Connected",
  "settings.modelsFound": "models found",
  "settings.notConnected": "Could not connect",
  "settings.localModelLabel": "Model",
  "settings.autoBySize": "Automatic (by RAM)",

  "settings.customServer": "My own server (OpenAI-compatible)",
  "settings.customServerHint": "LM Studio · llama.cpp · vLLM · TGI",
  "settings.serverUrl": "Server address",
  "settings.modelName": "Model name",
  "settings.apiKeyOptional": "API key (if any)",

  "settings.roles": "Agent roles",
  "settings.rolesHint":
    "Assign each role to a different backend (cloud · local Ollama · your own server). Leave empty to use the active default.",
  "settings.role.default": "(default)",

  "weights.relevance": "Relevance",
  "weights.authority": "Authority",
  "weights.recency": "Recency",
  "weights.citation_impact": "Citation impact",
  "weights.evidence": "Evidence",

  "common.loading": "Loading…",
  "common.error": "Something went wrong",
  "common.retry": "Retry",
  "common.delete": "Delete",
  "common.open": "Open",

  "status.queued": "Queued",
  "status.running": "Running",
  "status.awaiting_approval": "Awaiting approval",
  "status.completed": "Completed",
  "status.finished": "Completed",
  "status.error": "Error",
  "status.cancelled": "Cancelled",
  "status.idle": "Idle",

  // ── About ────────────────────────────────────────────────────────
  "about.title": "How Advanced Web Search Works",
  "about.intro":
    "Advanced Web Search goes beyond popularity-ranked search: a multi-agent engine scans current, verified, high-quality sources, adversarially tests every claim against its sources, and produces a transparent, cited report. The flow diagrams below show how the system works end to end.",
  "about.openSource":
    "Advanced Web Search is open source and MIT-licensed. Contributions are very welcome.",

  "about.tab.overview": "Overview",
  "about.tab.agents": "Multi-Agent Flow",
  "about.tab.retrieval": "Retrieval",
  "about.tab.scoring": "Scoring",
  "about.tab.architecture": "Architecture",
  "about.tab.features": "Features",
  "about.tab.contribute": "Contribute",

  "about.lifecycle.title": "Request lifecycle",
  "about.lifecycle.caption":
    "The path a research request takes from the UI to the engine and back as a report. Live events stream over SSE.",

  "about.agents.title": "Multi-agent flow",
  "about.agents.caption":
    "The heart of the system: planning, moderation, optional human approval, parallel research, ranking, the gap loop, synthesis and verification.",

  "about.retrieval.title": "Retrieval pipeline",
  "about.retrieval.caption":
    "For each sub-question: from query expansion to multi-source fan-out, hybrid search and the 5-signal score.",

  "about.scoring.title": "Source scoring",
  "about.scoring.caption":
    "Five signals combine, weighted, into a 0–100 match score; sources below the threshold are dropped.",
  "about.scoring.formula":
    "final = 0.40·Relevance + 0.15·Authority + 0.15·Recency + 0.15·Citation + 0.15·Evidence (weights are configurable in Settings)",

  "about.architecture.title": "Architecture",
  "about.architecture.caption":
    "A React frontend, a FastAPI + LangGraph backend, and a single-file SQLite database (relational + sqlite-vec + FTS5).",

  "about.features.title": "Features",
  "about.feat.depth.title": "Depth presets",
  "about.feat.depth.desc": "One-click depth selection from Quick to Exhaustive.",
  "about.feat.hitl.title": "HITL plan approval",
  "about.feat.hitl.desc": "Edit and approve sub-questions before research starts.",
  "about.feat.gap.title": "Iterative gap loop",
  "about.feat.gap.desc": "Missing angles trigger a new research round automatically.",
  "about.feat.snowball.title": "Citation snowballing",
  "about.feat.snowball.desc": "Discovers new sources via the citation graph of strong ones.",
  "about.feat.bilingual.title": "Bilingual search",
  "about.feat.bilingual.desc": "Queries are expanded TR↔EN for broader coverage.",
  "about.feat.transparent.title": "Transparent scoring",
  "about.feat.transparent.desc":
    "Each source's score, 'why kept' rationale, and whether the report cites it are visible; inline [n] markers jump to the exact source.",
  "about.feat.verify.title": "Citation verification",
  "about.feat.verify.desc":
    "Every [n] citation is checked against the source's actual text (embedding + LLM): supported / partial / unsupported / unverifiable. Unsupported claims are routed back for re-research, and the certainty score is the share of claims their sources actually back.",
  "about.feat.disagreement.title": "Disagreement detection",
  "about.feat.disagreement.desc":
    "The report explicitly surfaces where sources conflict or remain uncertain, in a dedicated section.",
  "about.feat.diversity.title": "Source diversity",
  "about.feat.diversity.desc":
    "Domain diversity is measured; an echo-chamber warning fires when evidence concentrates in one domain.",
  "about.feat.trail.title": "Research trail",
  "about.feat.trail.desc":
    "Transparently track which queries were issued, how many hits each returned, and which sources were kept or dropped.",
  "about.feat.ask.title": "Ask the report",
  "about.feat.ask.desc":
    "After a report lands, ask follow-up questions answered only from that run's gathered sources — with the same clickable [n] citations.",
  "about.feat.console.title": "Live terminal/console",
  "about.feat.console.desc": "Every agent step streams to a real-time live console.",
  "about.feat.hybrid.title": "Hybrid LLM",
  "about.feat.hybrid.desc": "Toggle between cloud APIs and a local Ollama model.",
  "about.feat.embedding.title": "Local multilingual embedding",
  "about.feat.embedding.desc": "On-device embedding and reranking with bge-m3.",
  "about.feat.export.title": "Citation & report export",
  "about.feat.export.desc": "BibTeX, RIS, Markdown, CSL-JSON and printable HTML.",
  "about.feat.multilang.title": "Multi-language report",
  "about.feat.multilang.desc":
    "Get the report in one or more languages you choose, each generated in parallel.",

  "about.contribute.title": "Contribute",
  "about.contribute.intro":
    "Advanced Web Search is an open-source (MIT) project and we welcome your contributions. To get started:",
  "about.contribute.stack.title": "Tech stack",
  "about.contribute.stack.desc":
    "Frontend: React 19, Vite, Tailwind. Backend: Python, FastAPI, LangGraph, LiteLLM, fastembed (bge-m3). Data: single-file SQLite + sqlite-vec + FTS5.",
  "about.contribute.layout.title": "Project layout",
  "about.contribute.layout.desc":
    "backend/advanced_web_search/{graph/nodes, sources, retrieval, scoring, llm, api} · frontend/src",
  "about.contribute.dev.title": "Dev environment",
  "about.contribute.dev.desc": "Run the dev server: python scripts/dev.py",
  "about.contribute.tests.title": "Tests",
  "about.contribute.tests.desc": "Run the tests: pytest tests/",
  "about.contribute.ideas.title": "Good first contribution ideas",
  "about.contribute.idea1":
    "Add a new source provider by implementing the SourceProvider interface in backend/advanced_web_search/sources/.",
  "about.contribute.idea2":
    "Add a new agent node under graph/nodes, or improve an existing prompt.",
  "about.contribute.idea3":
    "Add a new UI language in i18n.ts, or improve the source scoring.",
};

const dicts: Record<Lang, Dict> = { tr, en };

export function t(key: string, lang: Lang): string {
  return dicts[lang]?.[key] ?? tr[key] ?? key;
}

const listeners = new Set<(l: Lang) => void>();

function readLang(): Lang {
  if (typeof localStorage === "undefined") return "tr";
  const v = localStorage.getItem(LS_KEY);
  return v === "en" ? "en" : "tr";
}

export function useLang(): {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
} {
  const [lang, setLangState] = useState<Lang>(readLang);

  useEffect(() => {
    const handler = (l: Lang) => setLangState(l);
    listeners.add(handler);
    return () => {
      listeners.delete(handler);
    };
  }, []);

  const setLang = useCallback((l: Lang) => {
    try {
      localStorage.setItem(LS_KEY, l);
    } catch {
      /* ignore */
    }
    if (typeof document !== "undefined") {
      document.documentElement.lang = l;
    }
    setLangState(l);
    listeners.forEach((fn) => fn(l));
  }, []);

  const translate = useCallback((key: string) => t(key, lang), [lang]);

  return { lang, setLang, t: translate };
}
