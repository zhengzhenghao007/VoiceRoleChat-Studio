"use strict";
import { createAudioLibrary } from "./audio.js";
(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("character-form");
  const fields = ["name", "description", "system_prompt", "reply_language", "translation_language",
    "show_original_text", "show_translated_text", "auto_play_voice", "emotional_responses"];
  const languages = {zh:"中文（中英混合）",ja:"日语（含英文）",en:"英语",ko:"韩语（含英文）",yue:"粤语（含英文）",
    all_zh:"纯中文",all_ja:"纯日语",all_ko:"纯韩语",all_yue:"纯粤语",auto:"自动多语言",auto_yue:"自动多语言（含粤语）"};
  const defaults = {name:"",description:"",system_prompt:"",reply_language:"English",translation_language:"English",
    show_original_text:true,show_translated_text:true,auto_play_voice:true,emotional_responses:true,voice_config:null};
  const state = {roles:[],models:[],original:null,activeId:null,dirty:false,draftEpoch:0,busy:false,busyKind:"",
    loadingRole:false,selectionToken:0,serviceToken:0,rolesToken:0,modelsToken:0,initialized:false,
    service:null,connected:false,rolesError:false,modelsError:false,recording:false};
  const tabs = ["characters","models","audio"];
  let audioLibrary = null;
  const canonical = (value) => JSON.stringify(value, (_, item) => item && typeof item === "object" && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map((key) => [key,item[key]])) : item);
  const equal = (first, second) => canonical(first) === canonical(second);
  const node = (tag, className, text) => {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    return result;
  };
  class APIError extends Error {
    constructor(message, status = 0) { super(message); this.status = status; }
  }
  function connection(connected) {
    state.connected = connected;
    $("connection").className = "connection " + (connected ? "connected" : "offline");
    $("connection-text").textContent = connected ? "后端已连接" : "后端未连接";
  }
  async function api(path, options = {}, timeout = 12000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(path, {...options, signal:controller.signal, cache:"no-store"});
      connection(true);
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = Array.isArray(data?.detail) ? data.detail.map((item) => item.msg).join("；") : data?.detail;
        throw new APIError(typeof detail === "string" ? detail : `请求失败（${response.status}）`, response.status);
      }
      if (data === null) throw new APIError("后端返回了无法读取的数据", 502);
      return data;
    } catch (error) {
      if (error instanceof APIError) throw error;
      connection(false);
      throw new APIError(error.name === "AbortError" ? "请求等待超时，请重新查询服务状态。" : "无法连接后端，请确认服务已启动后重试。");
    } finally { clearTimeout(timer); }
  }
  const jsonRequest = (method, body) => ({method, headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  function notice(text, error = false) {
    $("notice").textContent = text;
    $("notice").className = "notice" + (error ? " error" : "");
    $("notice").hidden = !text;
    $("reload-current").hidden = true;
  }
  function tab(name) {
    if (state.recording && name !== "audio") { notice("请先停止录音再切换工作区。"); return; }
    for (const current of tabs) {
      const selected = current === name;
      $("tab-" + current).setAttribute("aria-selected", String(selected));
      $("tab-" + current).tabIndex = selected ? 0 : -1;
      $(current + "-panel").hidden = !selected;
    }
    if (name === "audio") audioLibrary?.refresh();
  }
  function chooseValue(select, value) {
    if (![...select.options].some((option) => option.value === value)) select.add(new Option(value, value));
    select.value = value;
  }
  for (const id of ["prompt-language","text-language"]) {
    for (const [value,label] of Object.entries(languages)) $(id).add(new Option(label,value));
  }
  function readDraft() {
    const data = {};
    for (const key of fields) {
      const input = form.elements.namedItem(key);
      data[key] = input.type === "checkbox" ? input.checked : input.value.trim();
    }
    data.voice_config = $("voice-enabled").checked ? {
      version:1,model_id:$("voice-model").value,reference_audio:$("reference-audio").value.trim(),
      prompt_text:$("reference-text").value.trim(),prompt_lang:$("prompt-language").value,text_lang:$("text-language").value
    } : null;
    return data;
  }
  function changesFrom(original, draft) {
    const changes = {};
    for (const key of [...fields,"voice_config"]) if (!equal(draft[key],original[key])) changes[key] = draft[key];
    return changes;
  }
  function syncDraft(changed = false) {
    if (changed) state.draftEpoch += 1;
    state.dirty = Object.keys(changesFrom(state.original || defaults, readDraft())).length > 0;
    renderControls();
  }
  function renderModelOptions(selected = $("voice-model").value) {
    const select = $("voice-model");
    select.replaceChildren(new Option("请选择完整模型", ""));
    for (const model of state.models) {
      const option = new Option(model.name + (model.status === "incomplete" ? "（配对不完整）" : ""), model.id);
      option.disabled = model.status !== "ready";
      select.add(option);
    }
    if (selected && !state.models.some((model) => model.id === selected)) {
      const unavailable = new Option("原绑定模型（已不可用）", selected);
      unavailable.disabled = true;
      select.add(unavailable);
    }
    select.value = selected || "";
    renderModelHint();
  }
  function renderModelHint() {
    const selected = $("voice-model").value;
    const model = state.models.find((entry) => entry.id === selected);
    $("voice-model-hint").textContent = selected && (!model || model.status !== "ready")
      ? "此绑定目前不可用。可保留它编辑角色资料，或选择其他完整模型。"
      : (state.modelsError ? "模型列表读取失败，现有绑定仍会保留。" : "文件配对完成后仍需实际试听验证。");
  }
  function renderRoles() {
    const list = $("character-list");
    list.replaceChildren();
    for (const role of state.roles) {
      const button = node("button", "", role.name);
      button.type = "button";
      button.title = role.name;
      button.setAttribute("aria-pressed",String(role.id === state.activeId));
      button.disabled = state.busy;
      button.addEventListener("click", () => loadRole(role.id));
      const item = node("li"); item.append(button); list.append(item);
    }
    $("characters-empty").hidden = state.roles.length > 0 || state.rolesError;
    $("characters-error").hidden = !state.rolesError;
  }
  function clearAudio() {
    const audio = $("result-audio");
    audio.pause(); audio.removeAttribute("src"); audio.load();
    $("audio-result").hidden = true;
    $("audio-empty").hidden = false;
    $("download-audio").removeAttribute("href");
  }
  function applyRole(role) {
    state.original = role ? structuredClone(role) : null;
    state.activeId = role?.id || null;
    state.draftEpoch += 1;
    const data = role || defaults;
    for (const key of fields) {
      const input = form.elements.namedItem(key);
      if (input.type === "checkbox") input.checked = data[key];
      else if (input.tagName === "SELECT") chooseValue(input,data[key]);
      else input.value = data[key];
    }
    const voice = data.voice_config;
    $("voice-enabled").checked = Boolean(voice);
    renderModelOptions(voice?.model_id || "");
    $("reference-audio").value = voice?.reference_audio || "";
    $("reference-text").value = voice?.prompt_text || "";
    $("prompt-language").value = voice?.prompt_lang || "ja";
    $("text-language").value = voice?.text_lang || "ja";
    $("editor-context").textContent = role ? "角色设置" : "新角色";
    $("editor-title").textContent = role ? role.name : "创建一个角色";
    syncDraft(); renderRoles();
  }
  function allowDiscard() {
    return !state.dirty || window.confirm("放弃尚未保存的修改？");
  }
  async function loadRole(id, force = false) {
    if (state.busy || state.recording || (!force && id === state.activeId && !state.loadingRole) || !allowDiscard()) return;
    const token = ++state.selectionToken;
    state.loadingRole = true;
    clearAudio(); notice(""); renderControls();
    try {
      const role = await api("/api/characters/" + encodeURIComponent(id));
      if (token === state.selectionToken) applyRole(role);
    } catch (error) {
      if (token === state.selectionToken) notice("读取角色失败：" + error.message,true);
    } finally {
      if (token === state.selectionToken) { state.loadingRole = false; renderControls(); }
    }
  }
  function newRole() {
    if (state.busy || state.recording || !allowDiscard()) return;
    state.selectionToken += 1; state.loadingRole = false;
    applyRole(null); clearAudio(); notice(""); tab("characters"); $("character-name").focus();
  }
  async function refreshRoles(initial = false) {
    const token = ++state.rolesToken;
    $("characters-loading").hidden = false;
    try {
      const roles = await api("/api/characters");
      if (token !== state.rolesToken) return;
      state.roles = roles; state.rolesError = false;
      if (initial && !state.initialized && !state.dirty && state.selectionToken === 0) applyRole(roles[0] || null);
      renderRoles();
    } catch (error) {
      if (token !== state.rolesToken) return;
      state.rolesError = true; renderRoles();
    } finally {
      if (token === state.rolesToken) $("characters-loading").hidden = true;
    }
  }
  function useModel(model) {
    if (state.busy || state.loadingRole || model.status !== "ready") return;
    $("voice-enabled").checked = true;
    $("voice-model").value = model.id;
    renderModelHint(); syncDraft(true); tab("characters"); $("reference-audio").focus();
    notice("已选择模型。补齐参考音频与文本后保存角色。");
  }
  function renderModels() {
    const list = $("model-list"); list.replaceChildren();
    for (const model of state.models) {
      const row = node("article","model-row");
      const identity = node("div"); identity.append(node("h3","",model.name));
      identity.append(node("span","model-status" + (model.status !== "ready" ? " incomplete" : ""),
        model.status === "ready" ? "文件已配对" : "配对不完整"));
      const weights = node("div","weight-list");
      for (const [key,label] of [["gpt","GPT"],["sovits","SoVITS"]]) {
        const filename = model[key] ? model[key].split(/[\\/]/).pop() : "缺少权重";
        weights.append(node("p","",label + "：" + filename));
      }
      const button = node("button","","用于当前角色"); button.type = "button";
      button.disabled = model.status !== "ready" || state.busy || state.loadingRole;
      button.addEventListener("click", () => useModel(model));
      row.append(identity,weights,button); list.append(row);
    }
    $("models-summary").textContent = state.modelsError ? "暂时无法更新模型列表" : "共发现 " + state.models.length + " 个模型";
    $("models-error").hidden = !state.modelsError;
    $("models-empty").hidden = state.models.length > 0 || state.modelsError;
  }
  async function refreshModels(rescan = false) {
    const token = ++state.modelsToken;
    try {
      const data = await api(rescan ? "/api/models/refresh" : "/api/models");
      if (token !== state.modelsToken) return;
      state.models = data.models; state.modelsError = false;
    } catch (error) {
      if (token !== state.modelsToken) return;
      state.modelsError = true;
    }
    renderModels(); renderModelOptions(); syncDraft();
  }
  function renderService() {
    const service = state.service;
    let label = "服务状态读取失败";
    if (service) {
      if (service.state === "ready") label = service.managed ? "托管服务已就绪" : "外部服务，仅可查看";
      else label = {stopped:"服务已停止",starting:"服务正在启动",unavailable:service.managed ? "托管服务尚未就绪" : "CPU 服务未启动",failed:"服务启动或运行失败"}[service.state] || "服务状态未知";
    }
    $("service-state").textContent = label;
    $("service-detail").textContent = service?.state === "failed" ? service.detail :
      service?.state === "ready" && !service.managed ? "工作室不会接管或修改外部服务。" : "";
    renderControls();
  }
  async function refreshService() {
    if (state.busy) return;
    const token = ++state.serviceToken;
    try {
      const service = await api("/api/tts/service",{},5000);
      if (token === state.serviceToken) state.service = service;
    } catch (error) { if (token === state.serviceToken) state.service = null; }
    if (token === state.serviceToken) renderService();
  }
  function renderControls() {
    const disabled = state.busy || state.loadingRole || state.recording;
    $("editor-fields").disabled = disabled;
    const enabled = $("voice-enabled").checked;
    $("voice-fields").hidden = !enabled;
    for (const id of ["voice-model","reference-audio","reference-text","prompt-language","text-language"]) {
      $(id).disabled = !enabled;
      $(id).required = enabled;
    }
    const missingOriginal = state.original?.voice_config?.model_id === $("voice-model").value &&
      !state.models.some((model) => model.id === $("voice-model").value && model.status === "ready");
    if (missingOriginal) $("voice-model").required = false;
    $("reference-upload").disabled = !enabled || disabled;
    $("save-character").disabled = disabled || !state.dirty;
    $("save-character").textContent = state.busyKind === "save" ? "保存中…" : "保存角色";
    $("draft-state").textContent = state.loadingRole ? "读取中…" : state.dirty ? "有未保存修改" : state.activeId ? "已保存" : "尚未保存";
    $("draft-state").className = "draft-state" + (state.dirty ? " dirty" : "");
    $("revision-label").textContent = state.original ? "修订 " + state.original.revision : "名称与提示词为必填项";
    for (const id of ["new-character","refresh-characters","characters-retry","refresh-models","reload-current"]) $(id).disabled = state.busy || state.recording;
    for (const button of $("character-list").querySelectorAll("button")) button.disabled = state.busy || state.recording;
    for (const [index,button] of [...$("model-list").querySelectorAll("button")].entries()) button.disabled = disabled || state.models[index]?.status !== "ready";
    const service = state.service;
    $("start-service").disabled = disabled || !state.connected || !service || service.managed || ["ready","starting"].includes(service.state);
    $("stop-service").disabled = disabled || !service?.managed || service.state === "starting";
    $("start-service").textContent = state.busyKind === "start" ? "正在启动…" : "启动 CPU 服务";
    $("stop-service").textContent = state.busyKind === "stop" ? "正在停止…" : "停止服务";
    const canGenerate = state.activeId && state.original?.voice_config && !state.dirty && service?.managed && service.state === "ready";
    $("generate-audio").disabled = disabled || !canGenerate || !$("audition-text").value.trim();
    $("generate-audio").textContent = state.busyKind === "generate" ? "正在生成…" : "生成试听";
    $("audition-text").disabled = state.busy;
    $("audition-hint").textContent = state.busyKind === "generate" ? "正在生成，请等待。CPU 推理可能需要一段时间。" :
      state.dirty ? "有未保存修改，请先保存后试听。" : !state.activeId ? "先创建并保存一个角色。" :
      !state.original.voice_config ? "先为角色绑定模型和参考音频。" : service?.state === "ready" && !service.managed ? "外部服务仅可查看，请使用工作室托管服务。" :
      !canGenerate ? "启动 CPU 服务后，即可生成试听。" : "使用这个角色已保存的声音配置。";
    for (const name of tabs) $("tab-"+name).disabled = state.recording && name !== "audio";
    audioLibrary?.renderControls();
  }
  async function busy(kind, task, onError) {
    if (state.busy || state.recording) return;
    state.busy = true; state.busyKind = kind; renderControls();
    try { await task(); }
    catch (error) { if (onError) onError(error); else notice(error.message,true); }
    finally { state.busy = false; state.busyKind = ""; renderControls(); }
  }
  async function save(event) {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const draft = readDraft();
    const original = state.original;
    const body = original ? {...changesFrom(original,draft),expected_revision:original.revision} : draft;
    if (original && Object.keys(body).length === 1) { notice("没有需要保存的修改。"); return; }
    const selection = state.selectionToken, epoch = state.draftEpoch;
    await busy("save",async () => {
      const result = await api(original ? "/api/characters/" + original.id : "/api/characters",jsonRequest(original ? "PATCH" : "POST",body));
      if (selection !== state.selectionToken) return;
      state.roles = [result,...state.roles.filter((role) => role.id !== result.id)];
      if (state.draftEpoch === epoch) { applyRole(result); notice("角色已保存"); }
      else {
        state.original = structuredClone(result); state.activeId = result.id;
        syncDraft(); renderRoles(); notice("提交时的内容已保存，后续修改仍保留在表单中。");
      }
      $("characters-empty").hidden = true;
    }, (error) => {
      if (error.status === 409 && /revision changed/i.test(error.message)) {
        notice("角色修订发生冲突，请重新加载后再保存。当前草稿已保留。",true);
        $("reload-current").hidden = !state.activeId;
      } else notice("保存失败：" + error.message,true);
    });
  }
  async function upload(event) {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    if (!/\.wav$/i.test(file.name) || file.size > 10 * 1024 * 1024 || file.size === 0) {
      notice("请选择不超过 10 MiB 的非空 WAV 文件。",true); return;
    }
    const selection = state.selectionToken;
    await busy("upload",async () => {
      const body = new FormData(); body.append("file",file);
      const result = await api("/api/voices/upload",{method:"POST",body},180000);
      if (selection !== state.selectionToken) return;
      if (!/^uploads\/[0-9a-f]{32}\.wav$/i.test(result.file_path)) throw new APIError("上传返回的参考路径无效");
      $("reference-audio").value = result.file_path;
      syncDraft(true); notice("参考音频已上传。填写对应文字后保存角色，保存时会验证音频。");
    },error => notice("上传失败：" + error.message,true));
  }
  async function serviceAction(action) {
    state.serviceToken += 1;
    await busy(action,async () => {
      state.service = await api("/api/tts/service/" + action,{method:"POST"},700000);
      renderService(); notice(action === "start" ? "CPU 服务已启动，可以生成试听。" : "自有服务已停止。");
    },error => notice((error.status === 504 ? "服务操作超时，请查询状态后重新启动。" : "服务操作失败：" + error.message),true));
    await refreshService();
  }
  async function generate() {
    if (state.dirty || !state.activeId || !state.original?.voice_config || state.busy) return;
    const selection = state.selectionToken, id = state.activeId, name = state.original.name;
    state.serviceToken += 1;
    clearAudio();
    await busy("generate",async () => {
      const result = await api("/api/characters/" + id + "/synthesize",jsonRequest("POST",{text:$("audition-text").value.trim()}),700000);
      if (selection !== state.selectionToken || id !== state.activeId) return;
      if (!/^\/api\/tts\/audio\/[0-9a-f]{32}$/.test(result.audio_url)) throw new APIError("合成返回的音频地址无效");
      $("result-audio").src = result.audio_url;
      $("audio-label").textContent = name + " 的试听";
      $("audio-meta").textContent = Number(result.duration_seconds).toFixed(2) + " 秒，" + (Number(result.sample_rate)/1000) + " kHz";
      $("download-audio").href = result.audio_url;
      $("download-audio").download = "voicerole-" + result.id + ".wav";
      $("audio-result").hidden = false; $("audio-empty").hidden = true;
      notice("试听已生成，点击播放器播放。");
    },error => notice(error.status === 504 ? "合成超时，自有服务已尝试清理，请重新启动后再试。" : "生成失败：" + error.message,true));
    await refreshService();
  }
  form.addEventListener("input",() => { renderModelHint(); syncDraft(true); });
  form.addEventListener("change",() => { renderModelHint(); syncDraft(true); });
  form.addEventListener("submit",save);
  $("reference-upload").addEventListener("change",upload);
  $("new-character").addEventListener("click",newRole);
  $("refresh-characters").addEventListener("click",() => refreshRoles());
  $("characters-retry").addEventListener("click",() => refreshRoles());
  $("refresh-models").addEventListener("click",() => refreshModels(true));
  $("reload-current").addEventListener("click",() => state.activeId && loadRole(state.activeId,true));
  $("start-service").addEventListener("click",() => serviceAction("start"));
  $("stop-service").addEventListener("click",() => serviceAction("stop"));
  $("generate-audio").addEventListener("click",generate);
  $("audition-text").addEventListener("input",renderControls);
  for (const [index,name] of tabs.entries()) {
    $("tab-" + name).addEventListener("click",() => tab(name));
    $("tab-" + name).addEventListener("keydown",(event) => {
      if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
      event.preventDefault();
      const target = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length-1] :
        tabs[(index+(event.key === "ArrowRight" ? 1 : -1)+tabs.length)%tabs.length];
      tab(target); $("tab-" + target).focus();
    });
  }
  window.addEventListener("beforeunload",(event) => {
    if (state.dirty || audioLibrary?.hasPendingRecording()) { event.preventDefault(); event.returnValue = ""; }
  });
  audioLibrary=createAudioLibrary({api,jsonRequest,busy,notice,isBusy:()=>state.busy || state.loadingRole,
    onRecordingChange:(active)=>{state.recording=active;renderControls();},
    useReference:(path)=>{
      if (state.busy || state.loadingRole || state.recording || !/^uploads\/[0-9a-f]{32}\.wav$/.test(path)) return;
      $("voice-enabled").checked=true;
      if ($("reference-audio").value !== path) $("reference-text").value="";
      $("reference-audio").value=path;syncDraft(true);tab("characters");$("reference-text").focus();
      notice("参考音频已填入草稿。请填写对应文字、选择模型并保存角色。");
    }});
  applyRole(null);
  Promise.allSettled([refreshRoles(true),refreshModels(),refreshService(),audioLibrary.refresh(),api("/health")]).then(() => {
    state.initialized = true; renderControls();
  });
  setInterval(() => { if (!state.busy) refreshService(); },10000);
})();
