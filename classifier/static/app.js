"use strict";
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const labels = {queued:"Queued",running:"Classifying",review:"Ready to review",deferred:"Saved for later",apply_queued:"Approved · queued",applying:"Applying",applied:"Applied",error:"Needs attention",apply_error:"Check application",rejected:"Removed from queue",abandoned:"Closed after error"};
const terminal = new Set(["applied","rejected","abandoned"]);
let state = {jobs:[]}, taxonomy = {tags:[],types:[]}, documents = [], selected = new Set(), page = 1, query = "", currentView = "library", activeJob = null, activeRevision = null;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify(body)});
  if (response.status === 401) { location.href = "/login"; throw new Error("Please sign in again."); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || (typeof data.detail === "string" ? data.detail : "The request could not be completed."));
  return data;
}
function notice(message, error=false) { $("notice").textContent=message; $("notice").className=error?"error":""; $("notice").hidden=false; }
function safely(fn) { return async event => { try { await fn(event); } catch(error) { notice(error.message,true); } }; }
function badge(status) { return `<span class="badge ${escapeHTML(status)}">${escapeHTML(labels[status] || status)}</span>`; }
function documentURL(id) { return `${state.paperless_url}/documents/${Number(id)}/details`; }
function jobTitle(job) { return job.document_title || job.proposal?.before.title || `Document #${job.document_id}`; }
function removeButton(job) {
  if(terminal.has(job.status)) return "";
  return `<button class="small" data-remove="${job.id}" ${job.status==="applying"?'disabled title="Wait for the current changes to finish applying."':`title="${job.status==="apply_error"?"Close this entry in History; existing Paperless changes are kept.":"Move this entry to History. The document stays in Paperless."}"`}>Remove from queue</button>`;
}
function removedNotice() { notice("Removed from queue. The document and any existing changes remain in Paperless. The entry is in History."); }
function jobFor(id) { return state.jobs.find(job=>job.document_id===id); }
function selection() {
  $("selection-count").textContent=selected.size?`${selected.size} selected · up to 10 at a time`:"Select documents to begin";
  $("classify").disabled=!selected.size;
  $("select-all").checked=!!documents.length && documents.slice(0,10).every(doc=>selected.has(doc.id));
}
function renderDocuments() {
  const tags=new Map(taxonomy.tags.map(t=>[t.id,t.name])), types=new Map(taxonomy.types.map(t=>[t.id,t.name]));
  $("documents-body").innerHTML=documents.length?documents.map(doc=>{
    const job=jobFor(doc.id);
    return `<tr><td><input type="checkbox" data-document="${doc.id}" aria-label="Select ${escapeHTML(doc.title)}" ${selected.has(doc.id)?"checked":""}></td><td class="document-name"><a href="${escapeHTML(documentURL(doc.id))}" target="_blank" rel="noopener">${escapeHTML(doc.title || "Untitled document")}</a><span class="doc-sub">Document #${doc.id} · ${escapeHTML(new Date(doc.added).toLocaleDateString())}</span></td><td>${escapeHTML(types.get(doc.document_type)||"Unassigned")}</td><td>${doc.tags.map(id=>`<span class="badge">${escapeHTML(tags.get(id)||`#${id}`)}</span>`).join("")||"—"}</td><td>${job?`<button class="text-button" data-open="${job.id}">${badge(job.status)}</button>`:"<span class=muted>Not classified</span>"}</td></tr>`;
  }).join(""):'<tr><td colspan="5">No matching documents.</td></tr>';
  selection();
}
async function loadDocuments() {
  const result=await api(`/api/documents?page=${page}&query=${encodeURIComponent(query)}`);
  documents=result.results; selected.clear();
  $("document-count").textContent=result.count;
  $("previous").disabled=page===1; $("next").disabled=!result.next; $("page-number").textContent=`Page ${page}`;
  renderDocuments();
}
function renderJobs() {
  const reviews=state.jobs.filter(j=>!terminal.has(j.status)), history=state.jobs.filter(j=>terminal.has(j.status));
  const ready=reviews.filter(j=>j.status==="review").length;
  $("review-count").textContent=reviews.length; $("pending-count").textContent=ready;
  $("applied-count").textContent=history.filter(j=>j.status==="applied").length;
  for (const [id,jobs] of [["review-list",reviews],["history-list",history]]) {
    $(id).innerHTML=jobs.length?jobs.map(job=>`<article class="job-card"><div>${badge(job.status)}<h3>${escapeHTML(jobTitle(job))}</h3><p>${escapeHTML(job.error || (job.proposal?`${job.proposal.source==="vision"?"Read with vision":"Paperless OCR"} · ${job.proposal.new_tags.length} new tag suggestions${job.proposal.cached?" · cached result":""}`:"Waiting for the worker"))}</p></div><div class="job-actions"><button data-open="${job.id}">${job.status==="review"?"Review proposal":"View details"} →</button><a class="outline-link small" href="${escapeHTML(documentURL(job.document_id))}" target="_blank" rel="noopener">Original ↗</a>${removeButton(job)}</div></article>`).join(""):`<div class="empty-state"><h2>${id==="review-list"?"All caught up":"Your filing history starts here"}</h2><p class="muted">${id==="review-list"?"Select documents from your library to prepare a proposal.":"Applied and removed entries appear here. The latest 200 history entries are shown. All active jobs remain in the queue."}</p></div>`;
  }
  $("paused-banner").hidden=!state.paused;
  $("pause-button").textContent=state.paused?"Resume processing":"Pause processing";
  $("paperless-link").href=state.paperless_url;
  $("intake-error").textContent=state.intake_error||"";
}
async function refresh() { state=await api("/api/state"); renderJobs(); renderDocuments(); }
function setView(view) {
  currentView=view;
  const headings={library:["Your documents","Turn a stack of documents into a collection that makes sense."],review:["A second look","Check the suggestions, then choose what to apply."],history:["Filed & remembered","A record of the proposals you have handled."],settings:["Make it your own","Set up intake and give your tags a little more meaning."]};
  document.querySelectorAll("[data-view]").forEach(button=>button.classList.toggle("active",button.dataset.view===view));
  for (const name of Object.keys(headings)) $(`${name}-view`).hidden=name!==view;
  $("page-title").textContent=headings[view][0]; $("page-description").textContent=headings[view][1];
  $("breadcrumb").textContent=`Your workspace / ${view==="library"?"Documents":view[0].toUpperCase()+view.slice(1)}`;
  if (view==="settings") renderSettings();
}
function renderSettings() {
  $("intake-tag").innerHTML='<option value="">Choose a tag</option>'+taxonomy.tags.map(t=>`<option value="${t.id}">${escapeHTML(t.name)}</option>`).join("");
  $("intake-tag").value=state.intake.tag_id||""; $("intake-enabled").checked=state.intake.enabled;
  $("intake-enrich").checked=state.intake.enrich; $("intake-vision").checked=state.intake.vision_fallback;
  const previous=$("definition-tag").value;
  $("definition-tag").innerHTML=taxonomy.tags.map(t=>`<option value="${t.id}">${escapeHTML(t.name)}</option>`).join("");
  if(previous) $("definition-tag").value=previous;
  loadDefinition();
}
function loadDefinition() { $("definition-text").value=taxonomy.tags.find(t=>t.id===Number($("definition-tag").value))?.definition||""; }
function renderTagChoices(proposal,editable,approval) {
  const relevant=t=>t.probability>=.5||proposal.before.tags.includes(t.id);
  const checked=t=>approval?approval.tag_ids.includes(t.id)||proposal.before.tags.includes(t.id):relevant(t);
  const choice=t=>`<label class="tag-choice"><input type="checkbox" name="tag" value="${t.id}" ${checked(t)?"checked":""} ${editable?"":"disabled"}>${escapeHTML(t.name)}<span>${(t.probability*100).toFixed(0)}%</span></label>`;
  const main=proposal.tags.filter(relevant), rest=proposal.tags.filter(t=>!relevant(t));
  return (main.map(choice).join("")||'<p class="muted">No likely matches.</p>')+(rest.length?`<details class="technical"><summary>Other tag scores (${rest.length})</summary>${rest.map(choice).join("")}</details>`:"");
}
function renderSubjects(proposal,editable,approval) {
  const subjects=proposal.subjects||proposal.new_tags;
  if(!subjects.length) return '<p class="muted">No additional filing subjects were suggested.</p>';
  return subjects.map((subject,i)=>{
    const choice=approval?.subject_choices?.find(c=>c.index===i);
    const approved=approval?.selected_new_tags?.find(c=>c.index===i);
    const legacyIndex=proposal.new_tags.findIndex((s,index)=>(s.subject_index??index)===i);
    const checked=!!choice||!!approved||!!approval?.new_tag_indices?.includes(legacyIndex);
    const target=choice?choice.existing_tag_id:(subject.existing_tag_id??null);
    const match=proposal.taxonomy.tags.find(t=>t.id===subject.existing_tag_id);
    return `<div class="new-tag"><label class="tag-choice"><input type="checkbox" name="new-tag" value="${i}" ${checked?"checked":""} ${editable?"":"disabled"}>${escapeHTML(subject.name)}<span>${(subject.probability*100).toFixed(0)}%</span></label><p>${escapeHTML(subject.definition)}</p><blockquote>${escapeHTML(subject.evidence)}</blockquote><p class="fine-print">${match?`Suggested equivalent: ${escapeHTML(match.name)}. You can change this match.`:"No equivalent existing tag was suggested."}</p><label>Use subject as<select data-subject-target="${i}" ${editable?"":"disabled"}><option value="">Create a new tag</option>${proposal.taxonomy.tags.map(t=>`<option value="${t.id}" ${target===t.id?"selected":""}>Reuse ${escapeHTML(t.name)}</option>`).join("")}</select></label><label>New tag name<input data-subject-name="${i}" maxlength="80" value="${escapeHTML(approved?.name||choice?.name||subject.name)}" ${editable&&!target?"":"disabled"}></label></div>`;
  }).join("");
}
function openJob(id) {
  const job=state.jobs.find(j=>j.id===id); if(!job) return;
  activeJob=id; activeRevision=job.proposal_revision; const p=job.proposal, editable=["review","deferred"].includes(job.status);
  $("review-title").textContent=jobTitle(job);
  let fields="", footer="";
  if(p) {
    const currentTags=p.before.tags.map(id=>taxonomy.tags.find(t=>t.id===id)?.name||`#${id}`);
    fields=`<div class="review-grid"><section class="review-source"><div class="split-line"><h3>${p.source==="vision"?"Read with vision":"Document text"}</h3><a href="${escapeHTML(documentURL(job.document_id))}" target="_blank" rel="noopener">Open original ↗</a></div><pre>${escapeHTML(p.excerpt)}</pre>${p.excerpt_truncated?'<p class="fine-print">Showing the first 8,000 characters. Classification used the complete text.</p>':""}<details class="technical"><summary>Models & usage${p.cached?" · cached":""}</summary><pre>${escapeHTML(JSON.stringify(p.usage,null,2))}</pre><p>Cached results show usage from the original request.</p></details></section><section class="review-fields">${badge(job.status)}<label>Title<input id="proposal-title" maxlength="160" value="${escapeHTML(p.after?.title||job.approval?.title||p.title||p.before.title)}" ${editable?"":"disabled"}></label><p class="fine-print">Current: ${escapeHTML(p.before.title)}</p><label>Document type<select id="proposal-type" ${editable?"":"disabled"}><option value="">Keep current type</option>${p.taxonomy.types.map(t=>`<option value="${t.id}" ${(p.after?.document_type||job.approval?.document_type||p.type?.id)===t.id?"selected":""}>${escapeHTML(t.name)}</option>`).join("")}</select></label><p class="fine-print">Current: ${escapeHTML(taxonomy.types.find(t=>t.id===p.before.document_type)?.name||"Unassigned")}${p.type_answer?` · Jev: ${escapeHTML(p.type?.name||"Unknown")}, ${(p.type_answer.confidence*100).toFixed(0)}% provider confidence`:""}</p><h3>Existing tags</h3><p class="fine-print">Already on this document: ${escapeHTML(currentTags.join(", ")||"none")}. These are preserved.</p><div>${renderTagChoices(p,editable,job.approval)}</div><p class="probability-note">Jev relevance scores, not measured accuracy. Scores of 50% or higher are preselected for your review.</p><h3>Discovered subjects</h3><p class="fine-print">Select subjects to reuse an existing tag or create up to three new tags. You can rename a new tag while keeping its meaning. Scores describe the original subject; selections start unchecked.</p>${renderSubjects(p,editable,job.approval)}${job.approval?`<details class="technical"><summary>Approved changes & recorded result</summary><pre>${escapeHTML(JSON.stringify({approved:job.approval,after:p.after||p.observed_after_error||null},null,2))}</pre></details>`:""}</section></div>`;
  } else fields='<div class="review-fields"><p>'+escapeHTML(job.error||"This document is waiting for classification. You can close this window while it processes.")+"</p></div>";
  if(editable) footer='<button data-action="reject">Remove from queue</button><button data-action="defer">Save for later</button><button data-action="vision">Read with vision</button><button id="apply-proposal" class="primary">Apply selected changes</button>';
  if(["queued","running","apply_queued"].includes(job.status)) footer='<button data-action="reject">Remove from queue</button>';
  if(job.status==="error") footer='<button data-action="reject">Remove from queue</button><button data-action="vision">Read with vision</button><button data-action="retry" class="primary">Retry classification</button>';
  if(job.status==="apply_error") footer='<button data-action="abandon">Close without undoing changes</button><button data-action="reconcile" class="primary">Reconcile approved changes</button>';
  $("review-content").innerHTML=(job.error?`<p class="dialog-error">${escapeHTML(job.error)}${job.status==="apply_error"?" Changes may already exist in Paperless. Reconcile checks and completes the approved changes; closing keeps any changes already made.":""}</p>`:"")+fields+`<div id="dialog-message" role="alert" class="dialog-error" hidden></div><div class="dialog-footer">${footer||'<button data-action="close">Close</button>'}</div>`;
  if(!$("review-dialog").open) $("review-dialog").showModal();
}
async function performAction(action) {
  if(action==="close") { $("review-dialog").close(); return; }
  const job=state.jobs.find(j=>j.id===activeJob);
  const body=action==="vision"?{enrich:job.options.enrich,vision_fallback:true,force_vision:true}:{};
  await api(`/api/jobs/${activeJob}/${action==="vision"?"retry":action}`,body);
  $("review-dialog").close(); await refresh();
  if(["reject","abandon"].includes(action)) removedNotice(); else notice("Proposal updated.");
}
document.addEventListener("click",safely(async event=>{
  const remove=event.target.closest("[data-remove]");
  if(remove) {
    if(remove.disabled) return;
    remove.disabled=true;
    try {
      const job=state.jobs.find(j=>j.id===remove.dataset.remove);
      await api(`/api/jobs/${job.id}/${job.status==="apply_error"?"abandon":"reject"}`,{});
      await refresh(); removedNotice();
    } finally {remove.disabled=false;}
    return;
  }
  const nav=event.target.closest("[data-view]"); if(nav) setView(nav.dataset.view);
  const open=event.target.closest("[data-open]"); if(open) openJob(open.dataset.open);
}));
$("review-content").addEventListener("click",async event=>{
  const button=event.target.closest("button"); if(!button) return;
  const buttons=[...$("review-content").querySelectorAll("button")]; buttons.forEach(b=>b.disabled=true);
  try {
    if(button.id==="apply-proposal") {
      const title=$("proposal-title").value.trim(); if(!title) throw new Error("Enter a title before applying.");
      const tag_ids=[...document.querySelectorAll('input[name="tag"]:checked')].map(el=>Number(el.value));
      const subject_choices=[...$("review-content").querySelectorAll('input[name="new-tag"]:checked')].map(el=>{
        const index=Number(el.value), target=$("review-content").querySelector(`[data-subject-target="${index}"]`).value;
        return target?{index,existing_tag_id:Number(target)}:{index,name:$("review-content").querySelector(`[data-subject-name="${index}"]`).value.trim()};
      });
      await api(`/api/jobs/${activeJob}/apply`,{proposal_revision:activeRevision,title,tag_ids,subject_choices,document_type:$("proposal-type").value?Number($("proposal-type").value):null});
      $("review-dialog").close(); await refresh(); notice("Approved changes are queued. Completion will appear in History.");
    } else if(button.dataset.action) await performAction(button.dataset.action);
  } catch(error) { $("dialog-message").textContent=error.message; $("dialog-message").hidden=false; }
  finally { buttons.forEach(b=>b.disabled=false); }
});
$("review-content").addEventListener("change",event=>{
  if(event.target.matches("[data-subject-target]")) {
    $("review-content").querySelector(`[data-subject-name="${event.target.dataset.subjectTarget}"]`).disabled=!!event.target.value;
  }
});
$("close-dialog").onclick=()=>$("review-dialog").close();
$("documents-body").addEventListener("change",event=>{
  const id=Number(event.target.dataset.document); if(!id) return;
  if(event.target.checked && selected.size>=10) { event.target.checked=false; notice("Choose up to ten documents at a time.",true); return; }
  if(event.target.checked) selected.add(id); else selected.delete(id); selection();
});
$("select-all").onchange=event=>{selected=event.target.checked?new Set(documents.slice(0,10).map(d=>d.id)):new Set();renderDocuments();};
$("search-form").onsubmit=safely(async event=>{event.preventDefault();query=$("search").value.trim();page=1;await loadDocuments();});
$("previous").onclick=safely(async()=>{page--;await loadDocuments();});
$("next").onclick=safely(async()=>{page++;await loadDocuments();});
$("classify").onclick=safely(async()=>{
  $("classify").disabled=true;
  try {await api("/api/jobs",{document_ids:[...selected],enrich:$("enrich").checked,vision_fallback:$("vision").checked,force_vision:false});selected.clear();await refresh();setView("review");notice("Documents queued. You can keep browsing while they process.");}
  finally {selection();}
});
$("pause-button").onclick=safely(async()=>{await api("/api/pause",{});await refresh();});
$("logout").onclick=safely(async()=>{await api("/api/logout",{});location.href="/login";});
$("intake-form").onsubmit=safely(async event=>{event.preventDefault();await api("/api/intake",{enabled:$("intake-enabled").checked,tag_id:$("intake-tag").value?Number($("intake-tag").value):null,enrich:$("intake-enrich").checked,vision_fallback:$("intake-vision").checked});await refresh();notice("Intake settings saved.");});
$("create-intake-tag").onclick=safely(async()=>{await api("/api/intake/create-tag",{});taxonomy=await api("/api/taxonomy");await refresh();renderSettings();notice("classifier-queue is ready. Enable intake and save to start watching it.");});
$("definition-tag").onchange=loadDefinition;
$("definition-form").onsubmit=safely(async event=>{event.preventDefault();await api(`/api/tags/${$("definition-tag").value}/definition`,{definition:$("definition-text").value});taxonomy=await api("/api/taxonomy");notice("Tag definition saved for future classifications.");});
async function start() {
  try { [state,taxonomy]=await Promise.all([api("/api/state"),api("/api/taxonomy")]);renderJobs();await loadDocuments();
    if(!state.generative_ready) {$("enrich").checked=false;$("vision").checked=false;notice("Jev is ready. Configure the generative provider to enable title, new-tag, and vision suggestions.");}
  } catch(error) {notice(error.message,true);}
  setTimeout(tick,3000);
}
async function tick() {try{if(!document.hidden) await refresh();}catch(error){notice(error.message,true);}finally{setTimeout(tick,3000);}}
start();
