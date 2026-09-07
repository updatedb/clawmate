(function (global) {
  "use strict";

  function escHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatSize(bytes) {
    if (bytes === 0 || bytes == null) return "-";
    const units = ["B", "KB", "MB", "GB"];
    let index = 0;
    let value = bytes;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index++;
    }
    return `${value.toFixed(1)} ${units[index]}`;
  }

  function formatMtime(timestamp) {
    if (!timestamp) return "-";
    const date = new Date(timestamp * 1000);
    if (Number.isNaN(date.getTime())) return "-";
    return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  }

  function formatStatusText(text) {
    return text == null ? "" : String(text);
  }

  async function copyText(text, writeText) {
    if (typeof writeText !== "function") return false;
    await writeText(String(text));
    return true;
  }

  function showToast(message, setText, getText, delay = 2000) {
    const text = formatStatusText(message);
    setText(text);
    setTimeout(() => {
      if (!getText || getText() === text) setText("");
    }, delay);
    return text;
  }

  global.utils = Object.freeze({ escHtml, formatSize, formatMtime, formatStatusText, copyText, showToast });
})(window);
