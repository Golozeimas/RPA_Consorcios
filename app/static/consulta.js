"use strict";

const form = document.getElementById("consulta-form");
const button = document.getElementById("executar");
const estado = document.getElementById("estado");
const resultado = document.getElementById("resultado");
const envioForm = document.getElementById("envio-form");
const enviarButton = document.getElementById("enviar");
let execucaoAtual = null;

const estadosEnvio = {
  ACEITO: "Mensagem aceita pelo WhatsApp. A entrega ao destinatário ainda não foi confirmada.",
  ENVIANDO: "Envio em processamento ou aguardando confirmação. Não repita o envio.",
  INCERTO: "Resultado incerto. Verifique no provedor antes de tentar outro envio.",
  ERRO: "Falha no envio.",
};

async function atualizarEnvios(id) {
  try {
    const envios = await lerResposta(await fetch(`/api/consultas/${encodeURIComponent(id)}/envios`));
    if (execucaoAtual !== id) return;
    const lista = document.getElementById("envio-historico");
    lista.replaceChildren();
    for (const envio of envios) {
      const item = document.createElement("li");
      item.textContent = `${new Date(envio.data_hora).toLocaleString("pt-BR")} — ***${envio.destinatario.slice(-4)} — ${envio.erro || estadosEnvio[envio.status]}`;
      lista.append(item);
    }
  } catch {
    if (execucaoAtual === id) document.getElementById("envio-estado").textContent = "Não foi possível carregar o histórico de envios.";
  }
}

function mostrarEstado(mensagem, estilo) {
  estado.textContent = mensagem;
  estado.className = `alert alert-${estilo}`;
  estado.hidden = false;
}

async function lerResposta(response) {
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : "Informe parâmetros válidos.");
  }
  return payload;
}

function campo(label, valor) {
  const lista = document.getElementById("resultado-campos");
  const titulo = document.createElement("dt");
  titulo.textContent = label;
  const conteudo = document.createElement("dd");
  conteudo.textContent = valor ?? "Não disponível";
  lista.append(titulo, conteudo);
}

function numero(valor) {
  return valor === null ? "Não disponível" : Number(valor).toLocaleString("pt-BR");
}

function mostrarExecucao(execucao) {
  execucaoAtual = execucao.id;
  envioForm.hidden = true;
  document.getElementById("envio-estado").textContent = "";
  document.getElementById("envio-historico").replaceChildren();
  resultado.hidden = true;
  document.getElementById("resultado-campos").replaceChildren();
  const mensagem = document.getElementById("mensagem");
  mensagem.hidden = true;
  document.getElementById("mensagem-titulo").hidden = true;
  if (execucao.status === "SUCESSO" && execucao.dados_extraidos) {
    const item = execucao.dados_extraidos;
    campo("Fonte", item.fonte);
    if ("periodo_referencia" in item) {
      campo("Administradora", item.administradora ?? "Não disponível no conjunto agregado");
      campo("Período de referência", item.periodo_referencia);
      campo("Abrangência", item.abrangencia);
      if (item.segmento) campo("Segmento", item.segmento);
      campo("Grupos ativos", numero(item.grupos_ativos));
      campo("Cotas ativas", numero(item.cotas_ativas));
      campo("Cotas contempladas (últimos 12 meses)", numero(item.cotas_contempladas));
      campo("Cotas comercializadas (últimos 12 meses)", numero(item.cotas_comercializadas));
      campo("Créditos comercializados", item.creditos_comercializados ?? "Não disponível");
      campo("Campos indisponíveis", item.campos_indisponiveis.join(", "));
      campo("Consultado em", new Date(item.data_consulta).toLocaleString("pt-BR"));
      if (execucao.mensagem_gerada) {
        mensagem.textContent = execucao.mensagem_gerada;
        mensagem.hidden = false;
        document.getElementById("mensagem-titulo").hidden = false;
      }
    } else {
      campo("Métrica", item.metrica);
      campo("Período", item.periodo);
      campo("Resultado", `${Number(item.valor).toLocaleString("pt-BR")} ${item.unidade}`);
      campo("Consultado em", new Date(item.consultado_em).toLocaleString("pt-BR"));
    }
    campo("Execução", execucao.id);
    if (execucao.mensagem_gerada) {
      mensagem.textContent = execucao.mensagem_gerada;
      mensagem.hidden = false;
      document.getElementById("mensagem-titulo").hidden = false;
      envioForm.hidden = false;
    }
    atualizarEnvios(execucao.id);
    resultado.hidden = false;
    mostrarEstado("Consulta concluída.", "success");
  } else if (execucao.status === "SEM_RESULTADO") {
    mostrarEstado("O BCB não retornou dados para os parâmetros informados.", "warning");
  } else if (execucao.status === "PROCESSANDO") {
    mostrarEstado("Esta consulta já está em processamento. Atualize o histórico para acompanhar.", "info");
  } else {
    mostrarEstado(execucao.erro || "Consulta duplicada. Consulte a execução original no histórico.", "danger");
  }
}

async function carregarExecucao(id) {
  const execucao = await lerResposta(await fetch(`/api/consultas/${encodeURIComponent(id)}`));
  mostrarExecucao(execucao);
}

async function atualizarHistorico() {
  const aviso = document.getElementById("historico-erro");
  try {
    const registros = await lerResposta(await fetch("/api/consultas"));
    const tbody = document.getElementById("historico");
    tbody.replaceChildren();
    for (const item of registros) {
      const row = document.createElement("tr");
      for (const valor of [new Date(item.data_hora).toLocaleString("pt-BR"), item.parametros.periodo, item.status]) {
        const cell = document.createElement("td");
        cell.textContent = valor;
        row.append(cell);
      }
      const cell = document.createElement("td");
      const detalhe = document.createElement("button");
      detalhe.type = "button";
      detalhe.className = "btn btn-link btn-sm";
      detalhe.textContent = item.duplicada_de ? "Ver original" : "Ver execução";
      detalhe.addEventListener("click", () => carregarExecucao(item.duplicada_de || item.id).catch(() => mostrarEstado("Não foi possível carregar a execução.", "danger")));
      cell.append(detalhe);
      row.append(cell);
      tbody.append(row);
    }
    aviso.textContent = registros.length ? "" : "Nenhuma consulta registrada.";
  } catch {
    aviso.textContent = "Não foi possível carregar o histórico. Tente atualizar novamente.";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (button.disabled) return;
  button.disabled = true;
  form.setAttribute("aria-busy", "true");
  resultado.hidden = true;
  mostrarEstado("Consultando Banco Central...", "info");
  try {
    const periodo = document.getElementById("periodo").value;
    const segmento = document.getElementById("segmento").value;
    const uf = document.getElementById("uf").value;
    const execucao = await lerResposta(await fetch("/api/consultas/mercado", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        administradora: document.getElementById("administradora").value,
        periodo: periodo || null, segmento: segmento || null, uf: uf || null,
      }),
    }));
    if (execucao.duplicada_de) {
      await carregarExecucao(execucao.duplicada_de);
    } else {
      mostrarExecucao(execucao);
    }
  } catch (error) {
    mostrarEstado(error instanceof TypeError ? "Falha de conexão. Consulte o histórico antes de tentar novamente." : error.message, "danger");
  } finally {
    button.disabled = false;
    form.setAttribute("aria-busy", "false");
    await atualizarHistorico();
  }
});

document.getElementById("atualizar").addEventListener("click", atualizarHistorico);
envioForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!execucaoAtual || enviarButton.disabled) return;
  const id = execucaoAtual;
  enviarButton.disabled = true;
  envioForm.setAttribute("aria-busy", "true");
  const aviso = document.getElementById("envio-estado");
  aviso.textContent = "Enviando WhatsApp...";
  try {
    const envio = await lerResposta(await fetch(`/api/consultas/${encodeURIComponent(id)}/envios`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({destinatario: document.getElementById("destinatario").value}),
    }));
    if (execucaoAtual === id) aviso.textContent = envio.erro || estadosEnvio[envio.status];
  } catch (error) {
    if (execucaoAtual === id) aviso.textContent = error instanceof TypeError
      ? "Falha de conexão. Consulte o histórico antes de tentar novamente." : error.message;
  } finally {
    enviarButton.disabled = false;
    envioForm.setAttribute("aria-busy", "false");
    await atualizarEnvios(id);
  }
});
atualizarHistorico();
