/* Built-in icon pack extracted from svg.html: 18 menu items × 4 variants. */
window.ICON_DATABASE = [
      {
        id: "dashboard",
        title: "1. Рабочий стол",
        variants: [
          // V1: Classic Grid/Widgets
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="primary" x="3" y="3" width="8" height="8" rx="2"/><rect class="secondary" x="13" y="3" width="8" height="5" rx="2"/><rect class="secondary" x="3" y="13" width="8" height="8" rx="2"/><rect class="primary" x="13" y="10" width="8" height="11" rx="2"/></svg>`,
          // V2: Speedometer / Analytics
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M4 18a9 9 0 1 1 16 0"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M12 14l3-4"/><circle class="primary" cx="12" cy="14" r="2"/><rect class="secondary" x="3" y="19" width="18" height="2" rx="1"/></svg>`,
          // V3: Column Dashboard
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="3" width="18" height="18" rx="3" fill-opacity="0.1" stroke-width="2" class="secondary-stroke"/><path class="primary" d="M7 11h2v6H7zM11 7h2v10h-2zM15 13h2v4h-2z"/></svg>`,
          // V4: Modular Nodes
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="primary" cx="6" cy="6" r="3"/><circle class="secondary" cx="18" cy="6" r="3"/><circle class="secondary" cx="6" cy="18" r="3"/><circle class="primary" cx="18" cy="18" r="3"/><path class="secondary-stroke" stroke-width="2" d="M9 6h6M6 9v6M18 9v6M9 18h6"/></svg>`
        ]
      },
      {
        id: "chat",
        title: "2. Чат",
        variants: [
          // V1: Classic Bubbles
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary" d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/><circle class="secondary" cx="8" cy="10" r="1.5"/><circle class="secondary" cx="12" cy="10" r="1.5"/><circle class="secondary" cx="16" cy="10" r="1.5"/></svg>`,
          // V2: Dual Overlay Bubbles
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M16 4H5c-1.1 0-2 .9-2 2v12l3-3h10c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2z"/><path class="primary" d="M9 10h10c1.1 0 2 .9 2 2v8l-3-3H9c-1.1 0-2-.9-2-2v-3c0-1.1.9-2 2-2z"/></svg>`,
          // V3: Modern Rounded Bubble with Dot
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="primary" x="3" y="4" width="18" height="14" rx="4"/><path class="primary" d="M7 18l-3 3v-3h3z"/><circle class="secondary" cx="8" cy="11" r="1.5"/><circle class="secondary" cx="12" cy="11" r="1.5"/><circle class="secondary" cx="16" cy="11" r="1.5"/></svg>`,
          // V4: Typing Wave Message
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M21 12c0 4.418-4.03 8-9 8-1.5 0-2.91-.325-4.14-.91L3 20l1.29-3.23C3.48 15.47 3 13.8 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M8 12h8M10 9l2 3-2 3"/></svg>`
        ]
      },
      {
        id: "projects",
        title: "3. Проекты",
        variants: [
          // V1: Folder with Sub-files
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/><rect class="primary" x="7" y="10" width="10" height="6" rx="1"/></svg>`,
          // V2: Project Layers / Stack
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M12 2L2 7l10 5 10-5-10-5z"/><path class="primary" d="M2 12l10 5 10-5M2 17l10 5 10-5" stroke-width="2" class="primary-stroke" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
          // V3: Kanban Board Cards
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="3" width="5" height="18" rx="1.5"/><rect class="primary" x="10" y="3" width="5" height="12" rx="1.5"/><rect class="secondary" x="17" y="3" width="5" height="15" rx="1.5"/></svg>`,
          // V4: Target / Milestone Project
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="secondary-stroke" stroke-width="2" cx="12" cy="12" r="9"/><circle class="primary" cx="12" cy="12" r="4"/><path class="primary-stroke" stroke-width="2" d="M12 3v3M12 18v3M3 12h3M18 12h3"/></svg>`
        ]
      },
      {
        id: "tasks",
        title: "4. Задачи",
        variants: [
          // V1: Checklist with Checks
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="4" width="18" height="16" rx="2" fill-opacity="0.2"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M7 9l2 2 4-4M7 15l2 2 4-4"/></svg>`,
          // V2: Task List with Bullet Points
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="primary" cx="5" cy="7" r="2"/><circle class="primary" cx="5" cy="12" r="2"/><circle class="primary" cx="5" cy="17" r="2"/><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M10 7h10M10 12h10M10 17h10"/></svg>`,
          // V3: Circular Progress Task
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary-stroke" stroke-width="3" stroke-linecap="round" d="M12 3a9 9 0 1 0 9 9"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4"/></svg>`,
          // V4: Clipboard Task
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M19 3h-4.18C14.4 1.84 13.3 1 12 1s-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4"/></svg>`
        ]
      },
      {
        id: "memory",
        title: "5. Память",
        variants: [
          // V1: RAM / Chip
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="primary" x="5" y="5" width="14" height="14" rx="2"/><path class="secondary-stroke" stroke-width="2" d="M2 9h3M2 15h3M19 9h3M19 15h3M9 2v3M15 2v3M9 19v3M15 19v3"/></svg>`,
          // V2: Brain Neural Network
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="primary" cx="6" cy="12" r="3"/><circle class="primary" cx="18" cy="12" r="3"/><circle class="secondary" cx="12" cy="6" r="3"/><circle class="secondary" cx="12" cy="18" r="3"/><path class="secondary-stroke" stroke-width="2" d="M8.5 10.5l2-3M13.5 7.5l2 3M15.5 13.5l-2 3M10.5 16.5l-2-3"/></svg>`,
          // V3: Database Slots
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="3" width="18" height="5" rx="1"/><rect class="primary" x="3" y="10" width="18" height="5" rx="1"/><rect class="secondary" x="3" y="17" width="18" height="5" rx="1"/><circle class="primary" cx="6" cy="5.5" r="1"/><circle class="secondary" cx="6" cy="12.5" r="1"/><circle class="primary" cx="6" cy="19.5" r="1"/></svg>`,
          // V4: Cloud Memory Sync
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96z"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M12 10v6M9 13l3-3 3 3"/></svg>`
        ]
      },
      {
        id: "models",
        title: "6. Модели",
        variants: [
          // V1: 3D Cube
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary" d="M12 2L2 7l10 5 10-5-10-5z"/><path class="secondary" d="M2 17l10 5V12L2 7v10z"/><path class="primary" opacity="0.7" d="M12 22l10-5V7l-10 5v10z"/></svg>`,
          // V2: AI Molecule / Nodes
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="primary" cx="12" cy="5" r="3"/><circle class="secondary" cx="5" cy="17" r="3"/><circle class="secondary" cx="19" cy="17" r="3"/><path class="primary-stroke" stroke-width="2" d="M10 7.5L6.5 14.5M14 7.5l3.5 7M7.5 17h9"/></svg>`,
          // V3: Geometry Pyramid
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary" d="M12 2L1 21h22L12 2z"/><path class="secondary" d="M12 2v19l10 0L12 2z"/></svg>`,
          // V4: Neural Layer Box
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary-stroke" stroke-width="2" x="3" y="3" width="18" height="18" rx="3"/><path class="primary" d="M7 7h4v4H7zM13 7h4v4h-4zM7 13h4v4H7z"/><circle class="secondary" cx="15" cy="15" r="2"/></svg>`
        ]
      },
      {
        id: "agents",
        title: "7. AI-агенты",
        variants: [
          // V1: Robot Head
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="primary" x="4" y="6" width="16" height="12" rx="3"/><circle class="secondary" cx="9" cy="11" r="2"/><circle class="secondary" cx="15" cy="11" r="2"/><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M10 15h4M12 2v4M2 12h2M20 12h2"/></svg>`,
          // V2: Bot with Sparkles
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="secondary" cx="12" cy="13" r="7"/><circle class="primary" cx="9" cy="12" r="1.5"/><circle class="primary" cx="15" cy="12" r="1.5"/><path class="primary" d="M12 2l1.2 2.8L16 6l-2.8 1.2L12 10l-1.2-2.8L8 6l2.8-1.2z"/></svg>`,
          // V3: Microchip Agent
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="primary" x="6" y="6" width="12" height="12" rx="2"/><circle class="secondary" cx="12" cy="12" r="3"/><path class="secondary-stroke" stroke-width="2" d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>`,
          // V4: User with AI Halo
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M8 3a8 8 0 0 1 8 0"/></svg>`
        ]
      },
      {
        id: "agent-roles",
        title: "8. Роли агентов",
        variants: [
          // V1: Badge / Shield Role
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/><path class="primary" d="M12 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6zm0 8c-2.0 0-6 1-6 3v1h12v-1c0-2-4-3-6-3z"/></svg>`,
          // V2: User Crown
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary" d="M5 16L3 5l5.5 3L12 4l3.5 4L21 5l-2 11H5z"/><circle class="secondary" cx="12" cy="18" r="3"/></svg>`,
          // V3: Mask / Identity
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary" d="M2 9c0 7 10 11 10 11s10-4 10-11c-2 0-4 1-5 2.5C15.5 10 13.5 9 12 9s-3.5 1-5-2.5C6 10 4 9 2 9z"/><circle class="secondary" cx="8" cy="13" r="1.5"/><circle class="secondary" cx="16" cy="13" r="1.5"/></svg>`,
          // V4: Hierarchical Hierarchy Tree
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="primary" x="9" y="2" width="6" height="5" rx="1"/><rect class="secondary" x="2" y="17" width="6" height="5" rx="1"/><rect class="secondary" x="16" y="17" width="6" height="5" rx="1"/><path class="secondary-stroke" stroke-width="2" d="M12 7v5M5 17v-5h14v5"/></svg>`
        ]
      },
      {
        id: "github",
        title: "9. GitHub",
        variants: [
          // V1: Classic Octocat Silhouette Dual
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary" d="M12 2A10 10 0 0 0 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.23.66-.5v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.87 1.52 2.34 1.07 2.91.83.1-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.92 0-1.11.38-2 1.03-2.71-.1-.25-.45-1.29.1-2.64 0 0 .84-.27 2.75 1.02.79-.22 1.65-.33 2.5-.33.85 0 1.71.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.35.2 2.39.1 2.64.65.71 1.03 1.6 1.03 2.71 0 3.82-2.34 4.66-4.57 4.91.36.31.69.92.69 1.85V21c0 .27.16.59.67.5C19.14 20.16 22 16.42 22 12A10 10 0 0 0 12 2z"/><circle class="secondary" cx="12" cy="13" r="3"/></svg>`,
          // V2: Git Branch Nodes
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="secondary" cx="6" cy="6" r="3"/><circle class="primary" cx="6" cy="18" r="3"/><circle class="primary" cx="18" cy="9" r="3"/><path class="secondary-stroke" stroke-width="2" d="M6 9v6M6 9c0 3 12 0 12 0"/></svg>`,
          // V3: Git Commit Pull Request
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="primary" cx="18" cy="18" r="3"/><circle class="secondary" cx="6" cy="6" r="3"/><circle class="secondary" cx="6" cy="18" r="3"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M6 9v6M18 15V9a3 3 0 0 0-3-3H9"/></svg>`,
          // V4: Fork Icon
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="primary" cx="12" cy="18" r="3"/><circle class="secondary" cx="6" cy="6" r="3"/><circle class="secondary" cx="18" cy="6" r="3"/><path class="primary-stroke" stroke-width="2" d="M12 15V11M12 11L6 8M12 11l6-3"/></svg>`
        ]
      },
      {
        id: "ssh",
        title: "10. SSH",
        variants: [
          // V1: Secure Terminal Key
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="2" y="4" width="20" height="16" rx="3"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M7 9l3 3-3 3M13 15h4"/><circle class="primary" cx="17" cy="8" r="1.5"/></svg>`,
          // V2: Keyhole Shield
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z"/><circle class="primary" cx="12" cy="10" r="2.5"/><path class="primary" d="M11 12.5h2v4h-2z"/></svg>`,
          // V3: RSA Key
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="primary-stroke" stroke-width="2" cx="7" cy="12" r="4"/><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M11 12h10M17 12v3M20 12v2"/></svg>`,
          // V4: Server Connection Remote
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="3" width="18" height="6" rx="1.5"/><rect class="secondary" x="3" y="15" width="18" height="6" rx="1.5"/><path class="primary-stroke" stroke-width="2" d="M12 9v6M9 12l3 3 3-3"/><circle class="primary" cx="6" cy="6" r="1"/><circle class="primary" cx="6" cy="18" r="1"/></svg>`
        ]
      },
      {
        id: "permissions",
        title: "11. Разрешения",
        variants: [
          // V1: Keylock Security
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="primary" x="5" y="11" width="14" height="10" rx="2"/><path class="secondary-stroke" stroke-width="2" d="M8 11V7a4 4 0 0 1 8 0v4"/><circle class="secondary" cx="12" cy="16" r="1.5"/></svg>`,
          // V2: User Shield Check
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/><circle class="primary" cx="18" cy="16" r="4"/><path class="secondary" d="M16.5 16l1 1 2-2" stroke="#fff" stroke-width="1.5"/></svg>`,
          // V3: Fingerprint Access
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M12 3a9 9 0 0 0-9 9c0 2 .5 3.5 1.5 5M21 12a9 9 0 0 0-14.5-7"/><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M12 7a5 5 0 0 0-5 5c0 3 1 4.5 2 7M17 12a5 5 0 0 0-7.5-4.3"/><circle class="primary" cx="12" cy="12" r="2"/></svg>`,
          // V4: Slider Toggle Switches
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="5" width="18" height="4" rx="2"/><circle class="primary" cx="16" cy="7" r="3"/><rect class="secondary" x="3" y="15" width="18" height="4" rx="2"/><circle class="primary" cx="8" cy="17" r="3"/></svg>`
        ]
      },
      {
        id: "system-instructions",
        title: "12. Системные инструкции",
        variants: [
          // V1: Document Prompt
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6z"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M8 12l2 2-2 2M12 16h4"/></svg>`,
          // V2: Book Rules
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M4 6h16v14H4z" fill-opacity="0.2"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6zM9 9h6M9 13h6M9 17h4"/></svg>`,
          // V3: Command Gear Code
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M8 9l-3 3 3 3M16 9l3 3-3 3"/><circle class="primary" cx="12" cy="12" r="3"/></svg>`,
          // V4: Checklist Bullet Directive
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="3" width="18" height="18" rx="2" fill-opacity="0.1"/><path class="primary" d="M7 7h2v2H7zM7 11h2v2H7zM7 15h2v2H7z"/><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M11 8h6M11 12h6M11 16h6"/></svg>`
        ]
      },
      {
        id: "recommendations",
        title: "13. Рекомендации",
        variants: [
          // V1: Magic Wand Light
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M3 21l10-10M12 3l1 2 2 1-2 1-1 2-1-2-2-1 2-1 1-2z"/><path class="secondary" d="M19 11l.8 1.8 1.8.8-1.8.8-.8 1.8-.8-1.8-1.8-.8 1.8-.8.8-1.8z"/></svg>`,
          // V2: Lightbulb Sparkle
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary" d="M9 21h6v-2H9v2zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7z"/><circle class="secondary" cx="12" cy="9" r="2.5"/></svg>`,
          // V3: Thumbs Up Star
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.58 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/><polygon class="primary" points="12,2 13.09,4.26 15.57,4.62 13.78,6.36 14.21,8.83 12,7.67 9.79,8.83 10.22,6.36 8.43,4.62 10.91,4.26"/></svg>`,
          // V4: Star Rating Badge
          `<svg viewBox="0 0 24 24" width="24" height="24"><polygon class="primary" points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/><polygon class="secondary" points="12,6 13.5,9 17,9.5 14.5,12 15,15.5 12,13.8 9,15.5 9.5,12 7,9.5 10.5,9"/></svg>`
        ]
      },
      {
        id: "interface-settings",
        title: "14. Настройки интерфейса",
        variants: [
          // V1: Sliders
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><circle class="primary" cx="4" cy="12" r="3"/><circle class="primary" cx="12" cy="10" r="3"/><circle class="primary" cx="20" cy="14" r="3"/></svg>`,
          // V2: Gear Cog
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58z"/><circle class="primary" cx="12" cy="12" r="3.5"/></svg>`,
          // V3: Layout Customizer Paint Palette
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M12 3a9 9 0 0 0-9 9c0 4.97 4.03 9 9 9 1.5 0 2.5-1.1 2.5-2.5 0-.6-.2-1.2-.6-1.6-.4-.4-.6-1-.6-1.6 0-1.2 1-2.2 2.2-2.2H17c2.8 0 5-2.2 5-5 0-5-4.5-9-10-9z"/><circle class="primary" cx="6.5" cy="11.5" r="1.5"/><circle class="primary" cx="9.5" cy="7.5" r="1.5"/><circle class="primary" cx="14.5" cy="7.5" r="1.5"/><circle class="primary" cx="17.5" cy="11.5" r="1.5"/></svg>`,
          // V4: Display Layout Grid Toggle
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="3" width="18" height="18" rx="3" fill-opacity="0.1" stroke-width="2" class="secondary-stroke"/><rect class="primary" x="6" y="6" width="5" height="5" rx="1"/><rect class="secondary" x="13" y="6" width="5" height="5" rx="1"/><rect class="secondary" x="6" y="13" width="5" height="5" rx="1"/><rect class="primary" x="13" y="13" width="5" height="5" rx="1"/></svg>`
        ]
      },
      {
        id: "system-log",
        title: "15. Журнал системы",
        variants: [
          // V1: Terminal File Log
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M13 3H6c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-5-5z"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M8 12h8M8 16h5"/></svg>`,
          // V2: Shield Security Logs
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary-stroke" stroke-width="2" d="M12 2L4 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-8-3z"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M8 10h8M8 14h5"/></svg>`,
          // V3: Time History Clock Log
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="secondary-stroke" stroke-width="2" cx="12" cy="12" r="9"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M12 7v5l3 3"/></svg>`,
          // V4: Console Output Stream
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="2" y="4" width="20" height="16" rx="2"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M6 8l3 3-3 3M11 14h7"/></svg>`
        ]
      },
      {
        id: "terminal",
        title: "16. Терминал",
        variants: [
          // V1: Prompt Window
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="2" y="3" width="20" height="18" rx="3"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M6 9l4 3-4 3M12 15h6"/></svg>`,
          // V2: Code Brackets Prompt
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="primary-stroke" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M8 6L2 12l6 6M16 6l6 6-6 6"/><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M14 4l-4 16"/></svg>`,
          // V3: Mini CLI Box
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="primary" x="3" y="5" width="18" height="14" rx="2"/><circle class="secondary" cx="6" cy="8" r="1"/><circle class="secondary" cx="9" cy="8" r="1"/><circle class="secondary" cx="12" cy="8" r="1"/><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M7 13l2 2-2 2M11 17h4"/></svg>`,
          // V4: Floating Shell Window
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" fill-opacity="0.2"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M7 10l3 2-3 2M12 14h4"/></svg>`
        ]
      },
      {
        id: "system-map",
        title: "17. Карта системы",
        variants: [
          // V1: Nodes Map Topology
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="primary" cx="12" cy="5" r="3"/><circle class="secondary" cx="5" cy="18" r="3"/><circle class="secondary" cx="19" cy="18" r="3"/><path class="primary-stroke" stroke-width="2" d="M12 8v4M12 12L5 15M12 12l7 3"/></svg>`,
          // V2: Geographic Map Pin
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M20.5 3l-6 2-6-2-6 2v15l6-2 6 2 6-2V3z" fill-opacity="0.3"/><path class="secondary-stroke" stroke-width="2" d="M20.5 3l-6 2-6-2-6 2v15l6-2 6 2 6-2V3zM9 3v15M15 5v15"/><circle class="primary" cx="15" cy="10" r="3"/></svg>`,
          // V3: Compass Navigation
          `<svg viewBox="0 0 24 24" width="24" height="24"><circle class="secondary-stroke" stroke-width="2" cx="12" cy="12" r="9"/><polygon class="primary" points="12,7 14.5,12 12,17 9.5,12"/></svg>`,
          // V4: Grid Coordinate Map
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary-stroke" stroke-width="2" x="3" y="3" width="18" height="18" rx="2"/><path class="secondary-stroke" stroke-width="1" d="M3 9h18M3 15h18M9 3v18M15 3v18"/><circle class="primary" cx="15" cy="9" r="3"/></svg>`
        ]
      },
      {
        id: "pages",
        title: "18. Страницы",
        variants: [
          // V1: Multi Pages Stack
          `<svg viewBox="0 0 24 24" width="24" height="24"><path class="secondary" d="M4 6h11v14H4z" fill-opacity="0.3"/><rect class="primary" x="9" y="3" width="11" height="14" rx="1"/><path class="secondary-stroke" stroke-width="2" stroke-linecap="round" d="M6 18h12"/></svg>`,
          // V2: Single Page Document Layout
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="4" y="3" width="16" height="18" rx="2" fill-opacity="0.1" class="secondary-stroke" stroke-width="2"/><path class="primary-stroke" stroke-width="2" stroke-linecap="round" d="M8 7h8M8 11h8M8 15h5"/></svg>`,
          // V3: Browser Web Page
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="2" y="4" width="20" height="16" rx="2"/><path class="primary" d="M2 8h20v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8z" fill-opacity="0.2"/><circle class="primary" cx="5" cy="6" r="1"/><circle class="primary" cx="8" cy="6" r="1"/></svg>`,
          // V4: Duplicate Copy Pages
          `<svg viewBox="0 0 24 24" width="24" height="24"><rect class="secondary" x="3" y="3" width="12" height="12" rx="2"/><rect class="primary" x="9" y="9" width="12" height="12" rx="2"/></svg>`
        ]
      }
    ];

window.PQRenderIcon = function(id, settings, sizeOverride) {
  const entry = (window.ICON_DATABASE || []).find(item => item.id === id);
  if (!entry) return '';
  const config = settings && typeof settings === 'object' ? settings : {};
  const variant = Number.isInteger(Number(config.variant)) && Number(config.variant) >= 0 && Number(config.variant) <= 3 ? Number(config.variant) : 0;
  const primary = /^#[0-9a-fA-F]{6}$/.test(config.primary || '') ? config.primary : '#3b82f6';
  const secondary = /^#[0-9a-fA-F]{6}$/.test(config.secondary || '') ? config.secondary : '#64748b';
  const size = Math.max(12, Math.min(64, Number(sizeOverride) || Number(config.size) || 24));
  let svg = typeof config.svg === 'string' && config.svg.trim() ? config.svg.trim() : (entry.variants[variant] || entry.variants[0]);
  if (!/^<svg\b[\s\S]*<\/svg>\s*$/i.test(svg)) return '';
  if (/<\s*(script|foreignObject|iframe|object|embed)\b/i.test(svg) ||
      /\son[a-z][\w:-]*\s*=/i.test(svg) ||
      /\b(?:href|xlink:href)\s*=\s*["']\s*(?:https?:|\/\/|javascript:|data:)/i.test(svg) ||
      /\burl\s*\(/i.test(svg)) return '';
  svg = svg.replace(/(<svg\b[^>]*?)\bwidth\s*=\s*["'][^"']*["']/i, '$1width="' + size + '"');
  if (!/\bwidth\s*=/.test(svg.slice(0, svg.indexOf('>')))) svg = svg.replace(/<svg\b/i, '<svg width="' + size + '"');
  svg = svg.replace(/(<svg\b[^>]*?)\bheight\s*=\s*["'][^"']*["']/i, '$1height="' + size + '"');
  if (!/\bheight\s*=/.test(svg.slice(0, svg.indexOf('>')))) svg = svg.replace(/<svg\b/i, '<svg height="' + size + '"');
  svg = svg.replace(/<([a-z][\\w:-]*)([^>]*)>/gi, (tag, name, rawAttrs) => {
    const classes = [];
    let attrs = rawAttrs.replace(/\\sclass\\s*=\\s*(["'])(.*?)\\1/gi, (_, quote, value) => {
      classes.push(...value.split(/\\s+/).filter(Boolean));
      return '';
    });
    const hasPrimary = classes.includes('primary');
    const hasSecondary = classes.includes('secondary');
    const hasPrimaryStroke = classes.includes('primary-stroke');
    const hasSecondaryStroke = classes.includes('secondary-stroke');
    const setAttr = (key, value) => {
      const escaped = String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
      const pattern = new RegExp("\\s" + key + "\\s*=\\s*([\"'])[^\"']*\\1", 'i');
      if (pattern.test(attrs)) attrs = attrs.replace(pattern, ' ' + key + '="' + escaped + '"');
      else attrs += ' ' + key + '="' + escaped + '"';
    };
    if (hasPrimary) setAttr('fill', primary);
    else if (hasSecondary) setAttr('fill', secondary);
    if (hasPrimaryStroke) setAttr('stroke', primary);
    else if (hasSecondaryStroke) setAttr('stroke', secondary);
    if ((hasPrimaryStroke || hasSecondaryStroke) && !hasPrimary && !hasSecondary) setAttr('fill', 'none');
    if (hasSecondary && !/\\sfill-opacity\\s*=/.test(attrs)) setAttr('fill-opacity', '0.7');
    return '<' + name + attrs + '>';
  });
  return svg.replace('<svg ', '<svg aria-hidden="true" focusable="false" ');
};
