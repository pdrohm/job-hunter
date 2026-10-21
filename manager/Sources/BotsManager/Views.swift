import BotsCore
import SwiftUI

let windowWidth: CGFloat = 430

struct RootView: View {
    @Bindable var model: AppModel

    var body: some View {
        Group {
            if let s = model.logService {
                LogView(model: model, service: s)
            } else {
                ListView(model: model)
            }
        }
        .frame(width: windowWidth)
        .onAppear { model.windowOpened() }
        .onDisappear { model.windowClosed() }
    }
}

// MARK: - List

struct ListView: View {
    @Bindable var model: AppModel
    @State private var contentHeight: CGFloat = 200

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let err = model.configError {
                Banner(text: err)
            }
            if model.groups.isEmpty {
                empty
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(model.groups) { g in
                            GroupSection(model: model, group: g)
                        }
                    }
                    .padding(.horizontal, 8)
                    .padding(.vertical, 10)
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { contentHeight = $0 }
                }
                .scrollBounceBehavior(.basedOnSize)
                .frame(height: min(contentHeight, 560))
            }
            Divider()
            Footer(model: model)
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "square.stack.3d.up.fill")
                .font(.system(size: 15))
                .foregroundStyle(.tint)
            Text("Bots Manager")
                .font(.system(size: 13, weight: .semibold))
            Spacer()
            Text(summary)
                .font(.system(size: 11))
                .foregroundStyle(model.failedCount > 0 ? Color.red : Color.secondary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    private var summary: String {
        guard model.loaded else { return "carregando…" }
        var parts = ["\(model.runningCount) rodando"]
        if model.failedCount > 0 { parts.append("\(model.failedCount) com erro") }
        return parts.joined(separator: " · ")
    }

    private var empty: some View {
        VStack(spacing: 6) {
            Image(systemName: "tray")
                .font(.system(size: 22))
                .foregroundStyle(.secondary)
            Text("Nenhum serviço ainda")
                .font(.system(size: 13, weight: .medium))
            Text("Clique em Editar serviços para adicionar.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 28)
    }
}

struct Banner: View {
    let text: String
    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            Text(text)
                .font(.system(size: 11))
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Color.orange.opacity(0.12))
    }
}

struct GroupSection: View {
    @Bindable var model: AppModel
    let group: ServiceGroup

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(group.name.uppercased())
                    .font(.system(size: 10.5, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .tracking(0.4)
                Text(count)
                    .font(.system(size: 10.5).monospacedDigit())
                    .foregroundStyle(.tertiary)
                Spacer()
                SmallTextButton(title: "Iniciar todos", icon: "play.fill") { model.startAll(group) }
                SmallTextButton(title: "Parar todos", icon: "stop.fill") { model.stopAll(group) }
            }
            .padding(.horizontal, 8)
            .padding(.bottom, 2)
            VStack(spacing: 0) {
                ForEach(group.services) { s in
                    ServiceRow(model: model, service: s)
                }
            }
            .padding(4)
            .background(.background.opacity(0.55), in: RoundedRectangle(cornerRadius: 9))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(.separator.opacity(0.6), lineWidth: 0.5))
        }
    }

    private var count: String {
        let on = group.services.filter { model.statuses[$0.id]?.state.isActive == true }.count
        return "\(on)/\(group.services.count)"
    }
}

struct SmallTextButton: View {
    let title: String
    let icon: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 3) {
                Image(systemName: icon).font(.system(size: 8))
                Text(title).font(.system(size: 11))
            }
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(hover ? Color.primary.opacity(0.08) : .clear, in: Capsule())
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .foregroundStyle(.secondary)
        .onHover { hover = $0 }
    }
}

// MARK: - Row

struct ServiceRow: View {
    @Bindable var model: AppModel
    let service: ServiceConfig
    @State private var hover = false

    private var status: ServiceStatus? { model.statuses[service.id] }
    private var busy: Bool { model.busy.contains(service.id) }

    var body: some View {
        HStack(spacing: 9) {
            ZStack {
                if busy {
                    ProgressView().controlSize(.mini).scaleEffect(0.8)
                } else {
                    StatusDot(state: status?.state ?? .unknown)
                }
            }
            .frame(width: 14, height: 14)

            VStack(alignment: .leading, spacing: 1) {
                Text(service.name)
                    .font(.system(size: 13, weight: .medium))
                    .lineLimit(1)
                Text(busy ? "aguarde…" : (status?.detail ?? "…"))
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                if let err = model.errors[service.id] {
                    HStack(alignment: .top, spacing: 4) {
                        Text(err)
                            .font(.system(size: 11))
                            .foregroundStyle(.red)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                            .textSelection(.enabled)
                        Button {
                            model.errors[service.id] = nil
                        } label: {
                            Image(systemName: "xmark.circle.fill").font(.system(size: 10))
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.tertiary)
                        .help("Fechar")
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            buttons
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(hover ? Color.primary.opacity(0.05) : .clear, in: RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
        .onHover { hover = $0 }
        .help(service.description ?? "")
    }

    private var stopTitle: String { service.kind == .launchd ? "Pausar" : "Parar" }
    private var startTitle: String { status?.state == .scheduled ? "Rodar agora" : "Iniciar" }

    private var buttons: some View {
        HStack(spacing: 1) {
            IconButton(icon: "play.fill", help: startTitle, enabled: !busy && (status?.canStart ?? false)) {
                model.perform(.start, service)
            }
            IconButton(icon: service.kind == .launchd ? "pause.fill" : "stop.fill", help: stopTitle,
                       enabled: !busy && (status?.canStop ?? false)) {
                model.perform(.stop, service)
            }
            IconButton(icon: "arrow.clockwise", help: "Reiniciar", enabled: !busy && canRestart) {
                model.perform(.restart, service)
            }
            if service.siteURL != nil {
                IconButton(icon: "globe", help: "Abrir site", enabled: true) { model.openSite(service) }
            } else {
                Color.clear.frame(width: 24, height: 24)
            }
            IconButton(icon: "doc.text", help: "Ver log", enabled: true) { model.logService = service }
            IconButton(icon: "folder", help: "Abrir pasta", enabled: true) { model.openFolder(service) }
        }
    }

    private var canRestart: Bool {
        guard let st = status else { return false }
        if service.kind == .launchd { return st.state != .notInstalled && st.state != .paused }
        return st.canStop || st.state == .failed
    }
}

struct StatusDot: View {
    let state: ServiceState

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 9, height: 9)
            .overlay(Circle().strokeBorder(.black.opacity(0.12), lineWidth: 0.5))
            .shadow(color: state.isActive ? color.opacity(0.6) : .clear, radius: 3)
            .help(label)
    }

    var color: Color {
        switch state {
        case .running: return .green
        case .warning: return .yellow
        case .scheduled: return .blue
        case .paused: return .orange
        case .failed: return .red
        case .stopped: return .gray
        case .notInstalled, .unknown: return .gray.opacity(0.35)
        }
    }

    var label: String {
        switch state {
        case .running: return "Rodando"
        case .warning: return "Atenção"
        case .scheduled: return "Agendado"
        case .paused: return "Pausado"
        case .failed: return "Falhou"
        case .stopped: return "Parado"
        case .notInstalled: return "Não instalado"
        case .unknown: return "…"
        }
    }
}

struct IconButton: View {
    let icon: String
    let help: String
    let enabled: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 11, weight: .medium))
                .frame(width: 24, height: 24)
                .background(hover && enabled ? Color.primary.opacity(0.1) : .clear, in: RoundedRectangle(cornerRadius: 5))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .foregroundStyle(enabled ? Color.primary.opacity(0.75) : Color.primary.opacity(0.2))
        .disabled(!enabled)
        .onHover { hover = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}

// MARK: - Footer

struct Footer: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Toggle("Abrir ao iniciar o Mac", isOn: Binding(
                    get: { model.launchAtLogin },
                    set: { model.setLaunchAtLogin($0) }
                ))
                .toggleStyle(.switch)
                .controlSize(.mini)
                .font(.system(size: 11))
                Spacer()
            }
            if let msg = model.loginMessage {
                Text(msg)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 4) {
                FooterButton(title: "Editar serviços", icon: "square.and.pencil") { model.editConfig() }
                FooterButton(title: "Recarregar", icon: "arrow.triangle.2.circlepath") { model.reload() }
                Spacer()
                FooterButton(title: "Sair", icon: "power") { NSApplication.shared.terminate(nil) }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
    }
}

struct FooterButton: View {
    let title: String
    let icon: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(.system(size: 12))
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(hover ? Color.primary.opacity(0.08) : .clear, in: RoundedRectangle(cornerRadius: 6))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

// MARK: - Log

struct LogView: View {
    @Bindable var model: AppModel
    let service: ServiceConfig
    @State private var text = ""
    @State private var path: String?

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 6) {
                Button {
                    model.logService = nil
                } label: {
                    Label("Voltar", systemImage: "chevron.left")
                        .font(.system(size: 12))
                }
                .buttonStyle(.plain)
                .foregroundStyle(.tint)
                Spacer()
                Text(service.name)
                    .font(.system(size: 13, weight: .semibold))
                    .lineLimit(1)
                Spacer()
                if let path {
                    IconButton(icon: "arrow.up.forward.app", help: "Abrir no Console", enabled: true) {
                        model.openInConsole(path)
                    }
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            Divider()
            ScrollViewReader { proxy in
                ScrollView {
                    Text(text.isEmpty ? "(log vazio)" : text)
                        .font(.system(size: 10.5, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                    Color.clear.frame(height: 1).id("end")
                }
                .frame(height: 420)
                .background(Color(nsColor: .textBackgroundColor).opacity(0.6))
                .onChange(of: text) { proxy.scrollTo("end", anchor: .bottom) }
            }
            Divider()
            HStack {
                Text(path.map { ($0 as NSString).abbreviatingWithTildeInPath } ?? "docker compose logs")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer()
                Text("últimas 200 linhas")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
        }
        .task(id: service.id) {
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func load() async {
        let s = service
        let result: (String?, String) = await offMain {
            if s.kind == .docker { return (nil, ServiceController.dockerLogs(s)) }
            guard let p = ServiceController.logPath(s) else { return (nil, "Sem arquivo de log. Ponha \"log\" em services.json.") }
            return (p, LogFile.tail(p) ?? "Log ainda não existe:\n\(p)")
        }
        path = result.0
        if text != result.1 { text = result.1 }
    }
}
