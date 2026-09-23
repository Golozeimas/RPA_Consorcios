"use strict";

const form = document.getElementById("consulta-form");
const button = document.getElementById("executar");
const estado = document.getElementById("estado");
const resultado = document.getElementById("resultado");

function mostrarEstado(mensagem, estilo) {
  estado.textContent = mensagem;
  estado.className = `alert alert-${estilo}`;
  estado.hidden = false;
}

async function lerResposta(response) {
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : "Informe um período válido no formato ano-mês.");
  }
  return payload;
}

function mostrarExecucao(execucao) {
  resultado.hidden = true;
  if (execucao.status === "SUCESSO" && execucao.dados_extraidos) {
    const item = execucao.dados_extraidos;
    document.getElementById("resultado-fonte").textContent = item.fonte;
    document.getElementById("resultado-metrica").textContent = item.metrica;
    document.getElementById("resultado-periodo").textContent = item.periodo;
    document.getElementById("resultado-valor").textContent = `${Number(item.valor).toLocaleString("pt-BR", {maximumFractionDigits: 10})} ${item.unidade}`;
    document.getElementById("resultado-data").textContent = new Date(item.consultado_em).toLocaleString("pt-BR");
    document.getElementById("resultado-id").textContent = execucao.id;
    resultado.hidden = false;
    mostrarEstado("Consulta concluída.", "success");
  } else if (execucao.status === "SEM_RESULTADO") {
    mostrarEstado("O BCB não retornou essa métrica para o período informado.", "warning");
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
    const execucao = await lerResposta(await fetch("/api/consultas", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({periodo: document.getElementById("periodo").value}),
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
atualizarHistorico();
