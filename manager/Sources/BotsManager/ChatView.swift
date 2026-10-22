import SwiftUI

struct ChatView: View {
    @Bindable var chat: ChatModel
    @Bindable var model: AppModel
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        if chat.messages.isEmpty { hint }
                        ForEach(chat.messages) { m in
                            MessageRow(message: m)
                        }
                        if chat.running {
                            HStack(spacing: 6) {
                                ProgressView().controlSize(.small)
                                Text("Claude está trabalhando…")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.leading, 4)
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .padding(12)
                }
                .onChange(of: chat.messages.count) { withAnimation { proxy.scrollTo("end", anchor: .bottom) } }
                .onChange(of: chat.running) { proxy.scrollTo("end", anchor: .bottom) }
                .onAppear { proxy.scrollTo("end", anchor: .bottom) }
            }
            Divider()
            input
        }
        .frame(minWidth: 420, minHeight: 420)
        .onAppear { focused = true }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "sparkles")
                .foregroundStyle(.tint)
            Text("Claude")
                .font(.system(size: 13, weight: .semibold))
            Text("usa o login do Claude Code deste Mac")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
            Spacer()
            FooterButton(title: "Nova conversa", icon: "plus.bubble") { chat.newChat() }
                .disabled(chat.running)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    private var hint: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Peça qualquer coisa, como no Claude Code.")
                .font(.system(size: 13, weight: .medium))
            Text("Ex.: \"por que o Apply bot falhou?\", \"reinicie o site\", \"adicione um serviço novo\".")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 8)
    }

    private var input: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("Mensagem para o Claude… (Enter envia, ⇧Enter nova linha)", text: $chat.draft, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .lineLimit(1...8)
                .focused($focused)
                .onKeyPress(.return, phases: .down) { press in
                    if press.modifiers.contains(.shift) { return .ignored }
                    send()
                    return .handled
                }
                .padding(8)
                .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(.separator, lineWidth: 0.5))
            if chat.running {
                Button { chat.stop() } label: {
                    Image(systemName: "stop.circle.fill").font(.system(size: 22))
                }
                .buttonStyle(.plain)
                .foregroundStyle(.red)
                .help("Parar")
            } else {
                Button { send() } label: {
                    Image(systemName: "arrow.up.circle.fill").font(.system(size: 22))
                }
                .buttonStyle(.plain)
                .foregroundStyle(.tint)
                .disabled(chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .help("Enviar")
            }
        }
        .padding(10)
    }

    private func send() {
        chat.send(services: model.services, configPath: model.configPath)
    }
}

struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        switch message.role {
        case .user:
            HStack {
                Spacer(minLength: 40)
                Text(message.text)
                    .font(.system(size: 13))
                    .textSelection(.enabled)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(Color.accentColor.opacity(0.18), in: RoundedRectangle(cornerRadius: 10))
            }
        case .assistant:
            Text(markdown(message.text))
                .font(.system(size: 13))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .tool:
            Label {
                Text(message.text)
                    .font(.system(size: 11, design: .monospaced))
                    .lineLimit(2)
                    .truncationMode(.tail)
            } icon: {
                Image(systemName: "wrench.and.screwdriver").font(.system(size: 9))
            }
            .foregroundStyle(.secondary)
            .padding(.leading, 4)
        case .error:
            Banner(text: message.text)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .textSelection(.enabled)
        }
    }

    private func markdown(_ s: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: s, options: options)) ?? AttributedString(s)
    }
}
