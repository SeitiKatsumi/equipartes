const $ = (id) => document.getElementById(id);

const state = {
  busy: false,
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
    button.disabled = value;
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
    setBusy(true, "Gerando carrossel");
    log("Iniciando geração. Isso pode levar vários minutos.", {
      outputPath: $("outputPath").value,
      slides: $("slideCount").value,
      style: $("styleId").value,
    });
    const data = await postJson("/api/generate-carousel", payload());
    log("Carrossel gerado", data);
  } catch (error) {
    log("Erro ao gerar carrossel", { error: error.message });
  } finally {
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

Use linguagem premium editorial, preto, laranja e branco.`;
});

$("clearLog").addEventListener("click", () => {
  $("logOutput").textContent = "";
});

log("Interface carregada");

