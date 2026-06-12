const $ = (id) => document.getElementById(id);

const state = {
  busy: false,
  pollTimer: null,
  currentJobId: null,
};

function log(message, data) {
  const time = new Date().toLocaleTimeString();
  const line = data ? `${time}  ${message}\n${JSON.stringify(data, null, 2)}` : `${time}  ${message}`;
  $("logOutput").textContent = `${line}\n\n${$("logOutput").textContent}`;
}

function setBusy(value, label = "Processando") {
  state.busy = value;
  $("apiState").textContent = value ? label : "Pronto";
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = value && button.id !== "clearLog";
  });
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || `Erro HTTP ${response.status}`);
  }
  return data;
}

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || `Erro HTTP ${response.status}`);
  }
  return data;
}

function payload() {
  return {
    assetsPath: $("assetsPath").value,
    outputPath: $("outputPath").value,
    slideCount: Number($("slideCount").value || 10),
    styleId: $("styleId").value,
    logoMode: $("logoMode").value,
    quality: $("quality").value,
    briefing: $("briefing").value,
    copyText: $("copyText").value,
  };
}

function resetProgress(total = 0) {
  $("progressLabel").textContent = `0/${total}`;
  $("progressStage").textContent = total ? "Preparando geração." : "Nenhuma geração em andamento.";
  $("progressBar").style.width = "0%";
  $("rawThumbs").innerHTML = "";
  $("finalThumbs").innerHTML = "";
}

function renderThumbs(containerId, images) {
  const container = $(containerId);
  const existing = new Set([...container.querySelectorAll("[data-index]")].map((node) => node.dataset.index));
  images.forEach((image) => {
    const key = String(image.index);
    if (existing.has(key)) return;
    const figure = document.createElement("figure");
    figure.className = "thumb";
    figure.dataset.index = key;
    const img = document.createElement("img");
    img.src = `${image.url}&t=${Date.now()}`;
    img.alt = `Slide ${image.index}`;
    const caption = document.createElement("figcaption");
    caption.textContent = String(image.index).padStart(2, "0");
    figure.append(img, caption);
    container.appendChild(figure);
  });
}

function updateProgress(job) {
  const total = Number(job.total || 0);
  const current = Number(job.current || 0);
  const doneCount = job.images?.length || 0;
  const percent = total ? Math.max((doneCount / total) * 100, (Math.max(current - 1, 0) / total) * 100) : 0;
  $("progressLabel").textContent = `${doneCount}/${total}`;
  $("progressStage").textContent = job.stage || "Processando.";
  $("progressBar").style.width = `${Math.min(100, percent)}%`;
  renderThumbs("rawThumbs", job.rawImages || []);
  renderThumbs("finalThumbs", job.images || []);
}

async function pollJob(jobId) {
  try {
    const job = await getJson(`/api/job-status?jobId=${encodeURIComponent(jobId)}`);
    updateProgress(job);
    if (job.status === "done") {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      setBusy(false);
      $("progressBar").style.width = "100%";
      log("Carrossel gerado", job.result);
      return;
    }
    if (job.status === "error") {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      setBusy(false);
      log("Erro ao gerar carrossel", { error: job.error });
    }
  } catch (error) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    setBusy(false);
    log("Erro ao acompanhar job", { error: error.message });
  }
}

$("scanAssets").addEventListener("click", async () => {
  try {
    setBusy(true, "Lendo assets");
    const data = await postJson("/api/scan-assets", { assetsPath: $("assetsPath").value });
    log("Assets encontrados", data);
  } catch (error) {
    log("Erro ao ler assets", { error: error.message });
  } finally {
    setBusy(false);
  }
});

$("generateCopy").addEventListener("click", async () => {
  try {
    setBusy(true, "Gerando copy");
    const data = await postJson("/api/generate-copy", payload());
    $("copyText").value = data.copy;
    log("Copy gerada", { chars: data.copy.length });
  } catch (error) {
    log("Erro ao gerar copy", { error: error.message });
  } finally {
    setBusy(false);
  }
});

$("generateCarousel").addEventListener("click", async () => {
  try {
    if (state.pollTimer) clearInterval(state.pollTimer);
    resetProgress(Number($("slideCount").value || 0));
    setBusy(true, "Gerando carrossel");
    log("Iniciando geração assíncrona.", {
      outputPath: $("outputPath").value,
      slides: $("slideCount").value,
      style: $("styleId").value,
    });
    const data = await postJson("/api/start-carousel", payload());
    state.currentJobId = data.jobId;
    log("Job iniciado", data);
    await pollJob(data.jobId);
    state.pollTimer = setInterval(() => pollJob(data.jobId), 3500);
  } catch (error) {
    log("Erro ao iniciar carrossel", { error: error.message });
    setBusy(false);
  }
});

$("sampleBrief").addEventListener("click", () => {
  $("briefing").value = `Crie um carrossel 4:5 sobre índices de meio-fundo e fundo.

01
ÍNDICES PARA MUNDIAIS E OLIMPÍADAS
MEIO-FUNDO E FUNDO
2026 • 2027 • 2028

02
COMO FUNCIONA A CLASSIFICAÇÃO?
Índice + Ranking Mundial + Vagas por país

03
MUNDIAL SUB-20 2026 MASCULINO
800m 1:50.00
1500m 3:47.50
3000m c/ obstáculos 9:00.00
5000m 14:08.00

Use linguagem premium editorial, com hierarquia clara e visual coerente com os assets.`;
});

$("clearLog").addEventListener("click", () => {
  $("logOutput").textContent = "";
});

resetProgress();
log("Interface carregada");
