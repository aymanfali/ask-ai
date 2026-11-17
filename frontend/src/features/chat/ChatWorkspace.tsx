import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ApiError, cancelGeneration, createConversation, deleteConversation, getGeneration, listConversations, listMessages, listModels, logout, renameConversation, streamGeneration } from "../../lib/api";
import type { Conversation, GenerationEvent, GenerationUsage, LLMModel, Message, User } from "../../lib/types";
import { Icon } from "../../components/Icon";
import { MarkdownContent } from "../../components/MarkdownContent";

interface ChatWorkspaceProps {
  user: User;
  onLogout: () => void;
}

interface ActiveGeneration {
  generationId: string | null;
  controller: AbortController;
  assistantMessageId: string | null;
  optimisticMessageId: string;
}

function makeId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "model_not_found") return "That model is no longer available. Choose another model.";
    if (error.code === "generation_in_progress") return "A response is already being generated in this conversation.";
    if (error.status === 429) return "The service is receiving too many requests. Please try again shortly.";
    if (error.status === 401) return "Your session has expired. Please sign in again.";
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

function relativeDate(value: string): string {
  const date = new Date(value);
  const now = new Date();
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const itemDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((day.getTime() - itemDay.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "Previous 7 days";
  return "Earlier";
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function usageLabel(usage: GenerationUsage): string {
  const tokens = usage.total_tokens !== null ? `${usage.total_tokens.toLocaleString()} tokens` : "Usage unavailable";
  const cost = usage.estimated_cost && usage.currency
    ? ` · ${usage.currency} ${Number(usage.estimated_cost).toFixed(4)}`
    : "";
  const estimated = usage.usage_source === "estimated" ? "Estimated · " : "";
  return `${estimated}${tokens}${cost}`;
}

export function ChatWorkspace({ user, onLogout }: ChatWorkspaceProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationCursor, setConversationCursor] = useState<string | null>(null);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messageCursor, setMessageCursor] = useState<number | null>(null);
  const [models, setModels] = useState<LLMModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [composer, setComposer] = useState("");
  const [search, setSearch] = useState("");
  const [loadingConversations, setLoadingConversations] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [sending, setSending] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [messageUsage, setMessageUsage] = useState<Record<string, GenerationUsage>>({});
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [lastActivity, setLastActivity] = useState<string | null>(null);
  const activeGeneration = useRef<ActiveGeneration | null>(null);
  const messageEndRef = useRef<HTMLDivElement | null>(null);
  const messagesViewportRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const selectedConversationRef = useRef<string | null>(null);
  const forceScrollToBottomRef = useRef(false);
  const skipInitialMessageLoadRef = useRef<string | null>(null);

  const selectedConversation = conversations.find((item) => item.id === selectedConversationId) ?? null;
  const selectedModel = models.find((item) => item.id === selectedModelId) ?? null;
  const filteredConversations = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    if (!term) return conversations;
    return conversations.filter((item) => item.title.toLocaleLowerCase().includes(term));
  }, [conversations, search]);
  const groupedConversations = useMemo(() => {
    const groups = new Map<string, Conversation[]>();
    for (const item of filteredConversations) {
      const group = relativeDate(item.updated_at);
      groups.set(group, [...(groups.get(group) ?? []), item]);
    }
    return [...groups.entries()];
  }, [filteredConversations]);

  const refreshConversations = useCallback(async (preserveSelection = true) => {
    const page = await listConversations({ limit: 50 });
    setConversations(page.items);
    setConversationCursor(page.next_cursor);
    if (!preserveSelection && page.items[0]) setSelectedConversationId(page.items[0].id);
    if (selectedConversationRef.current && !page.items.some((item) => item.id === selectedConversationRef.current)) {
      setSelectedConversationId(null);
      selectedConversationRef.current = null;
    }
  }, []);

  useEffect(() => {
    selectedConversationRef.current = selectedConversationId;
  }, [selectedConversationId]);

  useEffect(() => {
    let mounted = true;
    setLoadingConversations(true);
    Promise.all([listConversations({ limit: 50 }), listModels()])
      .then(([conversationPage, modelList]) => {
        if (!mounted) return;
        setConversations(conversationPage.items);
        setConversationCursor(conversationPage.next_cursor);
        setModels(modelList);
        setSelectedModelId((current) => current || modelList[0]?.id || "");
        if (conversationPage.items.length > 0) setSelectedConversationId(conversationPage.items[0].id);
        if (modelList.length === 0) setModelError("No models are configured. Add enabled provider and model entries to the backend LLM_PROVIDERS and LLM_MODELS settings.");
      })
      .catch((caught: unknown) => { if (mounted) setError(friendlyError(caught)); })
      .finally(() => { if (mounted) setLoadingConversations(false); });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!selectedConversationId) {
      setMessages([]);
      setMessageCursor(null);
      setLoadingMessages(false);
      return;
    }
    if (skipInitialMessageLoadRef.current === selectedConversationId) {
      skipInitialMessageLoadRef.current = null;
      return;
    }
    let mounted = true;
    forceScrollToBottomRef.current = true;
    setLoadingMessages(true);
    setMessages([]);
    setMessageCursor(null);
    listMessages(selectedConversationId, { limit: 50 })
      .then((page) => {
        if (!mounted) return;
        setMessages(page.items);
        setMessageCursor(page.next_before_sequence);
      })
      .catch((caught: unknown) => { if (mounted) setError(friendlyError(caught)); })
      .finally(() => { if (mounted) setLoadingMessages(false); });
    return () => { mounted = false; };
  }, [selectedConversationId]);

  useEffect(() => {
    const viewport = messagesViewportRef.current;
    if (!viewport) return;
    const closeToBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 180;
    if (forceScrollToBottomRef.current || closeToBottom) {
      forceScrollToBottomRef.current = false;
      messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages]);

  useEffect(() => {
    const textarea = composerRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
  }, [composer]);

  const chooseConversation = (id: string) => {
    if (sending) return;
    setSelectedConversationId(id);
    setMobileSidebarOpen(false);
    setError(null);
  };

  const startNewChat = () => {
    if (sending) return;
    setSelectedConversationId(null);
    setMessages([]);
    setMessageCursor(null);
    setComposer("");
    setError(null);
    setMobileSidebarOpen(false);
    composerRef.current?.focus();
  };

  useEffect(() => {
    const onShortcut = (event: globalThis.KeyboardEvent) => {
      const target = event.target;
      const isEditing = target instanceof HTMLElement && Boolean(
        target.closest("input, textarea, select, [contenteditable='true']"),
      );
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        startNewChat();
        return;
      }
      if (event.key === "/" && !isEditing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
      if (event.key === "Escape") setMobileSidebarOpen(false);
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, [sending]);

  const loadOlderMessages = async () => {
    if (!selectedConversationId || !messageCursor || loadingOlder) return;
    setLoadingOlder(true);
    const viewport = messagesViewportRef.current;
    const oldHeight = viewport?.scrollHeight ?? 0;
    try {
      const page = await listMessages(selectedConversationId, { limit: 50, beforeSequence: messageCursor });
      setMessages((current) => [...page.items, ...current]);
      setMessageCursor(page.next_before_sequence);
      requestAnimationFrame(() => {
        if (viewport) viewport.scrollTop = viewport.scrollHeight - oldHeight;
      });
    } catch (caught) {
      setError(friendlyError(caught));
    } finally {
      setLoadingOlder(false);
    }
  };

  const copyMessage = async (message: Message) => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
      window.setTimeout(() => setCopiedMessageId(null), 1400);
    } catch {
      setError("Clipboard access is unavailable in this browser context.");
    }
  };

  const performSend = async (rawContent: string) => {
    const content = rawContent.trim();
    if (!content || sending || !selectedModelId) return;
    setError(null);
    setSending(true);
    setCancelling(false);
    setComposer("");

    let conversationId = selectedConversationId;
    try {
      if (!conversationId) {
        const conversation = await createConversation();
        conversationId = conversation.id;
        skipInitialMessageLoadRef.current = conversationId;
        setSelectedConversationId(conversationId);
        setConversations((current) => [conversation, ...current]);
      }

      const optimisticMessageId = `local-${makeId()}`;
      const controller = new AbortController();
      const active: ActiveGeneration = {
        generationId: null,
        controller,
        assistantMessageId: null,
        optimisticMessageId,
      };
      activeGeneration.current = active;
      const optimisticMessage: Message = {
        id: optimisticMessageId,
        conversation_id: conversationId,
        role: "user",
        content,
        status: "complete",
        sequence: Date.now(),
        created_at: new Date().toISOString(),
        optimistic: true,
      };
      setMessages((current) => [...current, optimisticMessage]);
      setLastActivity("Preparing your response");

      await streamGeneration({
        conversationId,
        content,
        modelId: selectedModelId,
        idempotencyKey: makeId(),
        signal: controller.signal,
        onEvent: (event: GenerationEvent) => {
          if (event.type === "generation.started") {
            active.generationId = event.data.generation_id;
            active.assistantMessageId = event.data.assistant_message_id;
            setMessages((current) => {
              const next = current.map((message) => message.id === optimisticMessageId
                ? { ...message, id: event.data.user_message_id, sequence: event.data.assistant_sequence - 1, optimistic: false }
                : message);
              const exists = next.some((message) => message.id === event.data.assistant_message_id);
              if (!exists) next.push({
                id: event.data.assistant_message_id,
                conversation_id: conversationId!,
                role: "assistant",
                content: "",
                status: "streaming",
                sequence: event.data.assistant_sequence,
                created_at: new Date().toISOString(),
              });
              return next;
            });
            setLastActivity("Thinking");
          } else if (event.type === "message.delta") {
            setMessages((current) => current.map((message) => message.id === event.data.message_id
              ? { ...message, content: message.content + event.data.text, status: "streaming" }
              : message));
            setLastActivity("Writing");
          } else if (event.type === "generation.usage") {
            setLastActivity("Finishing");
          } else if (event.type === "stream.heartbeat") {
            setLastActivity("Thinking");
          } else if (event.type === "generation.completed") {
            if (event.data.usage && active.assistantMessageId) {
              setMessageUsage((current) => ({ ...current, [active.assistantMessageId!]: event.data.usage! }));
            }
            setMessages((current) => current.map((message) => message.id === event.data.message_id
              ? { ...message, status: "complete" }
              : message));
            setLastActivity(null);
          } else if (event.type === "generation.cancelled") {
            setMessages((current) => current.map((message) => message.id === event.data.message_id
              ? { ...message, status: "cancelled" }
              : message));
            setLastActivity(null);
          } else if (event.type === "generation.error") {
            void getGeneration(event.data.generation_id).then((generation) => {
              setMessages((current) => current.map((message) => message.id === generation.assistant_message_id
                ? { ...message, status: generation.status === "interrupted" ? "interrupted" : "failed" }
                : message));
            }).catch(() => {
              if (active.assistantMessageId) setMessages((current) => current.map((message) => message.id === active.assistantMessageId
                ? { ...message, status: "failed" }
                : message));
            });
            setError("The model could not complete this response. You can send the prompt again.");
            setLastActivity(null);
          }
        },
      });

      const [messagePage] = await Promise.all([
        listMessages(conversationId, { limit: 50 }),
        refreshConversations(),
      ]);
      setMessages(messagePage.items);
      setMessageCursor(messagePage.next_before_sequence);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) {
        setError(friendlyError(caught));
      }
      if (conversationId) {
        try {
          const page = await listMessages(conversationId, { limit: 50 });
          setMessages(page.items);
          setMessageCursor(page.next_before_sequence);
          await refreshConversations();
        } catch {
          // Preserve the original error shown to the user.
        }
      }
    } finally {
      activeGeneration.current = null;
      setSending(false);
      setCancelling(false);
      setLastActivity(null);
      composerRef.current?.focus();
    }
  };

  const submitComposer = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void performSend(composer);
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void performSend(composer);
    }
  };

  const stopGeneration = async () => {
    const active = activeGeneration.current;
    if (!active || cancelling) return;
    setCancelling(true);
    if (!active.generationId) {
      active.controller.abort();
      return;
    }
    try {
      await cancelGeneration(active.generationId);
      // The stream emits generation.cancelled after the worker observes the signal.
      // Bound the wait so a lost connection cannot leave the composer disabled forever.
      window.setTimeout(() => {
        if (activeGeneration.current === active && !active.controller.signal.aborted) active.controller.abort();
      }, 7000);
    } catch (caught) {
      setError(friendlyError(caught));
      active.controller.abort();
    }
  };

  const beginRename = (conversation: Conversation) => {
    setRenamingId(conversation.id);
    setRenameValue(conversation.title);
  };

  const saveRename = async (id: string) => {
    const title = renameValue.trim();
    if (!title) return;
    try {
      const updated = await renameConversation(id, title);
      setConversations((current) => current.map((item) => item.id === id ? updated : item));
      setRenamingId(null);
    } catch (caught) {
      setError(friendlyError(caught));
    }
  };

  const removeConversation = async (conversation: Conversation) => {
    if (!window.confirm(`Delete “${conversation.title}”? Its history will be hidden from your workspace.`)) return;
    try {
      await deleteConversation(conversation.id);
      setConversations((current) => current.filter((item) => item.id !== conversation.id));
      if (selectedConversationId === conversation.id) {
        setSelectedConversationId(null);
        setMessages([]);
      }
    } catch (caught) {
      setError(friendlyError(caught));
    }
  };

  const askAgain = (message: Message) => {
    const priorUserMessage = [...messages].reverse().find((item) => item.role === "user" && item.sequence < message.sequence);
    if (priorUserMessage) void performSend(priorUserMessage.content);
  };

  const handleLogout = async () => {
    try { await logout(); } catch (caught) { setError(friendlyError(caught)); }
    onLogout();
  };

  return (
    <main className={`workspace ${mobileSidebarOpen ? "workspace--sidebar-open" : ""}`}>
      <button className="mobile-scrim" type="button" aria-label="Close navigation" onClick={() => setMobileSidebarOpen(false)}/>
      <aside className="sidebar" aria-label="Conversation navigation">
        <div className="sidebar-top">
          <a className="brand" href="/" aria-label="Ask AI home"><span className="brand-mark"><Icon name="sparkles" size={18}/></span><span>ask<span className="brand-accent">.ai</span></span></a>
          <button className="icon-button sidebar-collapse" type="button" title="Close navigation" onClick={() => setMobileSidebarOpen(false)}><Icon name="panel"/></button>
        </div>
        <button type="button" className="new-chat-button" onClick={startNewChat} disabled={sending}><Icon name="plus" size={17}/>New chat<span className="new-chat-shortcut">Ctrl / ⌘ K</span></button>
        <label className="conversation-search"><Icon name="search" size={16}/><input ref={searchInputRef} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search conversations" aria-label="Search conversations"/><kbd>/</kbd></label>
        <div className="conversation-list" aria-label="Your conversations">
          {loadingConversations && <div className="conversation-skeletons"><i/><i/><i/><i/></div>}
          {!loadingConversations && groupedConversations.length === 0 && (
            <div className="sidebar-empty">{search ? "No conversations match your search." : "Your conversations will appear here."}</div>
          )}
          {groupedConversations.map(([group, items]) => (
            <section className="conversation-group" key={group}>
              <h2>{group}</h2>
              {items.map((conversation) => (
                <div className={`conversation-item ${selectedConversationId === conversation.id ? "is-selected" : ""}`} key={conversation.id}>
                  {renamingId === conversation.id ? (
                    <input className="rename-input" value={renameValue} autoFocus onChange={(event) => setRenameValue(event.target.value)} onBlur={() => void saveRename(conversation.id)} onKeyDown={(event) => { if (event.key === "Enter") void saveRename(conversation.id); if (event.key === "Escape") setRenamingId(null); }}/>
                  ) : (
                    <button className="conversation-select" type="button" onClick={() => chooseConversation(conversation.id)} title={conversation.title}>
                      <Icon name="message" size={15}/><span>{conversation.title}</span>
                    </button>
                  )}
                  <div className="conversation-actions">
                    <button type="button" title="Rename conversation" aria-label={`Rename ${conversation.title}`} onClick={() => beginRename(conversation)}><Icon name="edit" size={14}/></button>
                    <button type="button" title="Delete conversation" aria-label={`Delete ${conversation.title}`} onClick={() => void removeConversation(conversation)}><Icon name="trash" size={14}/></button>
                  </div>
                </div>
              ))}
            </section>
          ))}
          {conversationCursor && <button className="load-more-conversations" type="button" onClick={async () => {
            try {
              const page = await listConversations({ limit: 50, cursor: conversationCursor });
              setConversations((current) => [...current, ...page.items]);
              setConversationCursor(page.next_cursor);
            } catch (caught) { setError(friendlyError(caught)); }
          }}>Load older conversations</button>}
        </div>
        <div className="sidebar-bottom">
          <div className="privacy-note"><Icon name="shield" size={15}/><span>Your provider keys stay on the server.</span></div>
          <div className="account-row">
            <div className="avatar">{(user.display_name || user.email).slice(0, 1).toUpperCase()}</div>
            <div className="account-copy"><strong>{user.display_name || "Your account"}</strong><span>{user.email}</span></div>
            <button type="button" className="icon-button logout-button" title="Sign out" aria-label="Sign out" onClick={() => void handleLogout()}><Icon name="logout" size={17}/></button>
          </div>
        </div>
      </aside>

      <section className="chat-main">
        <header className="chat-topbar">
          <div className="chat-topbar__left">
            <button type="button" className="icon-button mobile-menu-button" aria-label="Open navigation" onClick={() => setMobileSidebarOpen(true)}><Icon name="menu"/></button>
            <div className="topbar-context"><span className="topbar-label">WORKSPACE</span><span className="topbar-separator">/</span><span className="topbar-title">{selectedConversation?.title ?? "New conversation"}</span></div>
          </div>
          <div className="chat-topbar__right">
            <label className="model-select-wrap">
              <span className="model-select-caption">MODEL</span>
              <select aria-label="Select model" value={selectedModelId} onChange={(event) => setSelectedModelId(event.target.value)} disabled={sending || models.length === 0}>
                {models.length === 0 && <option value="">No models configured</option>}
                {models.map((model) => <option key={model.id} value={model.id}>{model.provider_name} · {model.name}</option>)}
              </select>
              <span className="select-chevron"><Icon name="chevron" size={13}/></span>
            </label>
          </div>
        </header>

        {error && <div className="workspace-alert" role="alert"><span>{error}</span><button type="button" aria-label="Dismiss" onClick={() => setError(null)}><Icon name="x" size={15}/></button></div>}

        <div className={`messages-viewport ${messages.length === 0 ? "messages-viewport--empty" : ""}`} ref={messagesViewportRef}>
          {messageCursor && <button className="load-older-button" type="button" disabled={loadingOlder} onClick={() => void loadOlderMessages()}>{loadingOlder ? "Loading history…" : "Load older messages"}</button>}
          {loadingMessages && <div className="message-loading"><i/><i/><i/></div>}
          {!loadingMessages && messages.length === 0 && (
            <div className="welcome-panel">
              <div className="welcome-symbol"><Icon name="sparkles" size={28}/></div>
              <span className="eyebrow">A CLEARER WAY TO THINK</span>
              <h1>What can we<br/><span>work through?</span></h1>
              <p>Ask a question, explore an idea, or bring a difficult problem. Choose the model that fits the work.</p>
              <div className="prompt-grid">
                <button type="button" onClick={() => setComposer("Explain a complex topic in simple terms, with a practical example.")}><span className="prompt-icon prompt-icon--violet"><Icon name="sparkles" size={17}/></span><span><strong>Understand something</strong><small>Break down a complex idea</small></span><Icon name="arrow" size={15}/></button>
                <button type="button" onClick={() => setComposer("Help me plan a project. Ask the most important clarifying questions first.")}><span className="prompt-icon prompt-icon--blue"><Icon name="file" size={17}/></span><span><strong>Plan a project</strong><small>Turn an idea into clear steps</small></span><Icon name="arrow" size={15}/></button>
                <button type="button" onClick={() => setComposer("Review this code for correctness, maintainability, and edge cases: ")}><span className="prompt-icon prompt-icon--amber"><Icon name="code" size={17}/></span><span><strong>Review some code</strong><small>Find issues and improvements</small></span><Icon name="arrow" size={15}/></button>
                <button type="button" onClick={() => setComposer("Help me compare these options using clear criteria and trade-offs: ")}><span className="prompt-icon prompt-icon--green"><Icon name="globe" size={17}/></span><span><strong>Compare options</strong><small>See trade-offs clearly</small></span><Icon name="arrow" size={15}/></button>
              </div>
              {modelError && <div className="model-setup-note"><Icon name="shield" size={16}/>{modelError}</div>}
            </div>
          )}

          {messages.length > 0 && (
            <div className="message-thread" role="log" aria-live="polite" aria-relevant="additions text" aria-label="Conversation messages">
              {messages.map((message, index) => {
                const previousUser = message.role === "assistant" ? [...messages.slice(0, index)].reverse().find((item) => item.role === "user") : null;
                return (
                  <article className={`message-row message-row--${message.role}`} key={message.id}>
                    <div className={`message-avatar message-avatar--${message.role}`}>{message.role === "assistant" ? <Icon name="sparkles" size={17}/> : (user.display_name || user.email).slice(0, 1).toUpperCase()}</div>
                    <div className="message-body">
                      <div className="message-meta"><strong>{message.role === "assistant" ? "Ask AI" : user.display_name || "You"}</strong><time>{formatTime(message.created_at)}</time>{message.status === "streaming" && <span className="streaming-tag"><i/>Generating</span>}</div>
                      <div className={`message-content ${message.status === "failed" || message.status === "interrupted" ? "message-content--error" : ""}`}>
                        {message.content ? <MarkdownContent content={message.content}/> : message.status === "streaming" ? <span className="typing-indicator"><i/><i/><i/></span> : message.status === "pending" ? "Waiting for the model…" : "No response was saved."}
                      </div>
                      {message.status === "failed" && <p className="message-status-note">The response failed. You can run the original prompt again.</p>}
                      {message.status === "interrupted" && <p className="message-status-note">The stream was interrupted. The saved partial response is shown above.</p>}
                      {message.status === "cancelled" && <p className="message-status-note">Generation stopped.</p>}
                      <div className="message-toolbar">
                        <button type="button" onClick={() => void copyMessage(message)} aria-label="Copy message"><Icon name={copiedMessageId === message.id ? "check" : "copy"} size={14}/><span>{copiedMessageId === message.id ? "Copied" : "Copy"}</span></button>
                        {message.role === "assistant" && previousUser && !sending && <button type="button" onClick={() => askAgain(message)} title="Send the same prompt as a new conversation turn"><Icon name="refresh" size={14}/><span>Run prompt again</span></button>}
                      </div>
                      {message.role === "assistant" && messageUsage[message.id] && <div className="usage-line"><Icon name="clock" size={12}/>{usageLabel(messageUsage[message.id])}</div>}
                    </div>
                  </article>
                );
              })}
              {sending && <div className="generation-presence"><span className="presence-pulse"/>{lastActivity || "Working on your response"}</div>}
              <div ref={messageEndRef}/>
            </div>
          )}
        </div>

        <div className="composer-area">
          <form className="composer" onSubmit={submitComposer}>
            <textarea
              ref={composerRef}
              value={composer}
              onChange={(event) => setComposer(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder={selectedModel ? `Message ${selectedModel.name}…` : "Configure a model to start chatting…"}
              aria-label="Message Ask AI"
              rows={1}
              maxLength={32000}
              disabled={!selectedModel || sending}
            />
            <div className="composer-footer">
              <div className="composer-hints"><span><kbd>Enter</kbd> to send</span><span><kbd>Shift + Enter</kbd> for a new line</span></div>
              {sending ? (
                <button type="button" className="send-button send-button--stop" onClick={() => void stopGeneration()} disabled={cancelling} aria-label="Stop generation">
                  {cancelling ? <span className="spinner spinner--small"/> : <Icon name="stop" size={17}/>}<span>{cancelling ? "Stopping" : "Stop"}</span>
                </button>
              ) : (
                <button type="submit" className="send-button" disabled={!composer.trim() || !selectedModel} aria-label="Send message"><Icon name="send" size={17}/></button>
              )}
            </div>
          </form>
          <p className="composer-disclaimer">AI can make mistakes. Review important information before relying on it.</p>
        </div>
      </section>
    </main>
  );
}
