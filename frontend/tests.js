(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const runButton = byId("run");
  const copyReportButton = byId("copy-report");
  const copyShortButton = byId("copy-short");
  const status = byId("status");
  const progress = byId("progress");
  const output = byId("output");
  const groups = byId("groups");
  const groupCaption = byId("group-caption");
  let lastReport = null;

  const MODULE_NAMES = {
    test_agent_runtime: "Среда выполнения агентов",
    test_agent_tools: "Инструменты агентов",
    test_chat_agent_runtime: "Среда выполнения чат-агентов",
    test_conversation_store: "Хранилище диалогов",
    test_server: "Сервер и API"
  };

  function setMetric(id, value) {
    byId(id).textContent = value == null ? "—" : String(value);
  }

  function renderGroups(report) {
    const counts = new Map();
    const lines = String(report.output || "").split(/\r?\n/);
    const testLine = /^([\w-]+)\s+\(([^)]+)\)\s+\.\.\.\s+(ok|FAIL|ERROR)(?:\s|$)/;

    for (const line of lines) {
      const match = line.trim().match(testLine);
      if (!match) continue;
      const moduleMatch = match[2].match(/(?:^|\.)(test_[\w]+)(?:\.|$)/);
      const moduleName = moduleMatch ? moduleMatch[1] : "other";
      if (!counts.has(moduleName)) counts.set(moduleName, { total: 0, passed: 0, failures: 0, errors: 0 });
      const item = counts.get(moduleName);
      item.total += 1;
      if (match[3] === "ok") item.passed += 1;
      else if (match[3] === "FAIL") item.failures += 1;
      else item.errors += 1;
    }

    groups.replaceChildren();
    const entries = [...counts.entries()].sort((a, b) => {
      const aKnown = Object.prototype.hasOwnProperty.call(MODULE_NAMES, a[0]) ? 0 : 1;
      const bKnown = Object.prototype.hasOwnProperty.call(MODULE_NAMES, b[0]) ? 0 : 1;
      return aKnown - bKnown || a[0].localeCompare(b[0]);
    });

    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "В выводе не удалось определить результаты отдельных тестов.";
      groups.append(empty);
      groupCaption.textContent = "Нет данных по группам";
      return;
    }

    for (const [moduleName, item] of entries) {
      const card = document.createElement("div");
      card.className = "group " + (item.failures || item.errors ? "fail" : "ok");
      const mark = document.createElement("span");
      mark.className = "group-mark";
      const name = document.createElement("span");
      name.className = "group-name";
      name.textContent = MODULE_NAMES[moduleName] || moduleName;
      const count = document.createElement("span");
      count.className = "group-count";
      count.textContent = item.failures || item.errors
        ? `${item.passed}/${item.total} · ошибок: ${item.failures + item.errors}`
        : `${item.passed}/${item.total} успешно`;
      card.append(mark, name, count);
      groups.append(card);
    }
    groupCaption.textContent = `${entries.length} групп(ы)`;
  }

  function makeFullReport(report) {
    return [
      "PQlocalAgentOSv3 — отчёт общего теста",
      `Статус: ${report.ok ? "УСПЕШНО" : "ОШИБКА"}`,
      `Всего тестов: ${report.total ?? "?"}`,
      `Провалов: ${report.failures ?? 0}`,
      `Ошибок: ${report.errors ?? 0}`,
      `Код завершения: ${report.returncode ?? "?"}`,
      "",
      report.output || "(пустой вывод)"
    ].join("\n");
  }

  function makeShortReport(report) {
    return [
      `Общий тест: ${report.ok ? "УСПЕШНО" : "ОШИБКА"}`,
      `Тестов: ${report.total ?? "?"}; провалов: ${report.failures ?? 0}; ошибок: ${report.errors ?? 0}; код: ${report.returncode ?? "?"}`
    ].join("\n");
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("Браузер не разрешил копирование в буфер обмена.");
  }

  async function copyReport(short) {
    if (!lastReport) return;
    const button = short ? copyShortButton : copyReportButton;
    const originalText = button.textContent;
    try {
      await copyText(short ? makeShortReport(lastReport) : makeFullReport(lastReport));
      button.textContent = "Скопировано";
      window.setTimeout(() => { button.textContent = originalText; }, 1400);
    } catch (error) {
      status.textContent = "Не удалось скопировать: " + (error && error.message ? error.message : String(error));
      status.className = "status fail";
    }
  }

  runButton.addEventListener("click", async () => {
    runButton.disabled = true;
    copyReportButton.disabled = true;
    copyShortButton.disabled = true;
    status.textContent = "Выполняется… (до 5 минут)";
    status.className = "status";
    progress.className = "progress running";
    output.textContent = "Запускается набор тестов…";
    groups.replaceChildren();
    groupCaption.textContent = "Выполнение";
    setMetric("total", "…");
    setMetric("failures", "…");
    setMetric("errors", "…");
    setMetric("returncode", "…");
    lastReport = null;

    try {
      const response = await fetch("/api/tests/run", {
        method: "POST",
        headers: { "Accept": "application/json" },
        credentials: "same-origin"
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

      lastReport = {
        ok: Boolean(data.ok),
        total: data.total,
        failures: data.failures,
        errors: data.errors,
        returncode: data.returncode,
        output: data.output || data.error || "(пустой вывод)"
      };
      setMetric("total", lastReport.total);
      setMetric("failures", lastReport.failures ?? 0);
      setMetric("errors", lastReport.errors ?? 0);
      setMetric("returncode", lastReport.returncode);
      output.textContent = lastReport.output;
      renderGroups(lastReport);
      status.textContent = lastReport.ok ? "ТЕСТЫ ПРОЙДЕНЫ" : "ЕСТЬ ПРОБЛЕМЫ";
      status.className = "status " + (lastReport.ok ? "ok" : "fail");
      progress.className = "progress done";
      copyReportButton.disabled = false;
      copyShortButton.disabled = false;
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      status.textContent = "ОШИБКА ЗАПРОСА";
      status.className = "status fail";
      output.textContent = message;
      groups.replaceChildren();
      const item = document.createElement("div");
      item.className = "empty";
      item.textContent = "Не удалось получить результаты тестирования.";
      groups.append(item);
      groupCaption.textContent = "Запрос завершился ошибкой";
      progress.className = "progress";
    } finally {
      runButton.disabled = false;
    }
  });

  copyReportButton.addEventListener("click", () => copyReport(false));
  copyShortButton.addEventListener("click", () => copyReport(true));
})();
