"use strict";

// Fictional listings, salaries, and scores for the interface demo.
const jobs = [
  {
    id: 1,
    title: "Software Engineering Intern",
    company: "Google",
    logo: "google",
    letter: "G",
    location: "Mountain View, CA",
    type: "Internship",
    remote: false,
    salary: "$35–$48 / hour",
    match: 98,
    skills: ["Python", "Java", "Problem Solving"],
    description:
      "Work alongside engineers to build useful products and strengthen your software development skills.",
    requirements: [
      "Currently studying Computer Science or a related field.",
      "Experience with Python or Java.",
      "An interest in teamwork and solving technical problems."
    ]
  },
  {
    id: 2,
    title: "Junior Software Developer",
    company: "Microsoft",
    logo: "microsoft",
    letter: "M",
    location: "Redmond, WA",
    type: "Full-time",
    remote: false,
    salary: "$80,000–$105,000 / year",
    match: 95,
    skills: ["JavaScript", "Git", "SQL"],
    description:
      "Help develop and test applications while learning from an experienced engineering team.",
    requirements: [
      "Knowledge of programming fundamentals.",
      "Familiarity with Git and relational databases.",
      "Strong communication and collaboration skills."
    ]
  },
  {
    id: 3,
    title: "Frontend Developer Intern",
    company: "Spotify",
    logo: "spotify",
    letter: "S",
    location: "Remote",
    type: "Internship",
    remote: true,
    salary: "$28–$38 / hour",
    match: 92,
    skills: ["HTML", "CSS", "JavaScript"],
    description:
      "Create accessible interfaces and help improve the experience of discovering and enjoying music.",
    requirements: [
      "Basic experience building web pages.",
      "Familiarity with HTML, CSS, and JavaScript.",
      "An interest in accessible interface design."
    ]
  },
  {
    id: 4,
    title: "UX Design Intern",
    company: "Adobe",
    logo: "adobe",
    letter: "A",
    location: "San Jose, CA",
    type: "Internship",
    remote: false,
    salary: "$30–$40 / hour",
    match: 89,
    skills: ["Figma", "Prototyping", "User Research"],
    description:
      "Turn ideas into clear designs through research, wireframes, and interactive prototypes.",
    requirements: [
      "An interest in user experience and visual design.",
      "Experience with Figma or another design tool.",
      "A small portfolio of class or personal projects."
    ]
  },
  {
    id: 5,
    title: "Junior UI Engineer",
    company: "Figma",
    logo: "figma",
    letter: "F",
    location: "Remote",
    type: "Full-time",
    remote: true,
    salary: "$85,000–$110,000 / year",
    match: 87,
    skills: ["JavaScript", "CSS", "Accessibility"],
    description:
      "Build thoughtful interface components and collaborate with designers on new product experiences.",
    requirements: [
      "Experience creating responsive interfaces.",
      "Knowledge of JavaScript and CSS.",
      "An interest in accessibility and reusable components."
    ]
  },
  {
    id: 6,
    title: "IT Support Specialist",
    company: "Notion",
    logo: "notion",
    letter: "N",
    location: "New York, NY",
    type: "Full-time",
    remote: false,
    salary: "$55,000–$72,000 / year",
    match: 84,
    skills: ["Networking", "Troubleshooting", "Security"],
    description:
      "Support employees, troubleshoot technical issues, and help maintain secure workplace systems.",
    requirements: [
      "Understanding of computer hardware and networking.",
      "Strong troubleshooting and customer service skills.",
      "An interest in information security."
    ]
  }
];

const state = {
  page: "dashboard",
  filter: "All",
  search: "",
  saved: new Set(),
  applications: new Set(),
  resume: null,
  profile: {
    name: "Jamie Smith",
    email: "jamie@example.com",
    skills: "Python, Java, HTML, CSS",
    bio: "",
    education: true
  }
};

const $ = (selector) => document.querySelector(selector);

const escapeHTML = (value) =>
  String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);

// ICONS
const icons = {
  grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
  briefcase: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a22 22 0 0 0 18 0M12 12v3"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z"/>',
  building: '<rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1M10 21v-3h4v3"/>',
  book: '<path d="M12 5C8 2 3 3 3 3v16s5-1 9 2c4-3 9-2 9-2V3s-5-1-9 2zM12 5v16"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M14 15h2"/>',
  settings: '<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/><path d="m9 3-1 3-3 1-2 3 2 2-1 3 2 3 3-1 2 3h3l1-3 3-1 2-3-2-2 1-3-2-3-3 1-2-3z"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  search: '<circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 5 5"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  chevron: '<path d="m7 10 5 5 5-5"/>',
  upload: '<path d="M12 16V3M7 8l5-5 5 5M4 16v5h16v-5"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0z"/><circle cx="12" cy="10" r="2.5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  money: '<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M6 12h.01M18 12h.01"/>'
};

function icon(name) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${
    icons[name] || icons.briefcase
  }</svg>`;
}

function renderIcons() {
  document.querySelectorAll("[data-icon]").forEach((element) => {
    element.innerHTML = icon(element.dataset.icon);
  });
}

// THEME SWITCHING
const themeToggle = $("#theme-toggle");

function applyTheme(theme) {
  const dark = theme === "dark";

  document.documentElement.dataset.theme = dark ? "dark" : "light";
  themeToggle.setAttribute("aria-pressed", String(dark));
  themeToggle.title = dark
    ? "Switch to light theme"
    : "Switch to dark theme";

  themeToggle.querySelector(".theme-label").textContent =
    dark ? "Light theme" : "Dark theme";
}

applyTheme(document.documentElement.dataset.theme);

themeToggle.addEventListener("click", () => {
  const next =
    document.documentElement.dataset.theme === "dark"
      ? "light"
      : "dark";

  applyTheme(next);

  try {
    localStorage.setItem("jobportal-theme", next);
  } catch (_) {
    // Switching still works if browser storage is unavailable.
  }
});

// STATUS MESSAGES
let toastTimer;

function notify(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("show");

  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    $("#toast").classList.remove("show");
  }, 3500);
}

// PROFILE
function renderProfile() {
  const profile = state.profile;

  const initials = profile.name.trim().split(/\s+/)
    .slice(0, 2).map((part) => part[0]).join("").toUpperCase();

  $("#header-name").textContent = profile.name;
  $("#profile-name").textContent = profile.name;

  document.querySelectorAll(".avatar").forEach((avatar) => {
    avatar.textContent = initials;
  });

  const checks = [
    ["Add your name", Boolean(profile.name.trim())],
    ["Add your email", Boolean(profile.email.trim())],
    ["Add your education", profile.education],
    ["Add your skills", Boolean(profile.skills.trim())],
    ["Write a short bio", Boolean(profile.bio.trim())],
    ["Select your resume", Boolean(state.resume)]
  ];

  const completed = checks.filter(([, done]) => done).length;
  const percentage = Math.round(completed / checks.length * 100);

  $("#completion").textContent = `${percentage}%`;
  $("#profile-progress").value = completed;
  $("#profile-progress").textContent = `${percentage}%`;

  $(".small-tag").textContent =
    completed === checks.length ? "COMPLETE" : "KEEP GOING";

  $("#checklist").innerHTML = checks.map(([label, done]) => `
    <li>
      <span class="check-circle ${done ? "done" : ""}"
            aria-hidden="true">${done ? "✓" : ""}</span>
      ${label}${done ? '<span class="sr-only">, complete</span>' : ""}
    </li>
  `).join("");
}

// STATISTICS
function renderStats() {
  const stats = [
    {
      value: jobs.length,
      label: "Available opportunities",
      note: "Sample job listings",
      icon: "briefcase",
      color: "",
      page: "jobs"
    },
    {
      value: state.applications.size,
      label: "Demo applications",
      note: "Tracked in this session",
      icon: "file",
      color: "blue",
      page: "applications"
    },
    {
      value: state.saved.size,
      label: "Saved opportunities",
      note: "Your personal shortlist",
      icon: "heart",
      color: "purple",
      page: "saved"
    }
  ];

  $("#stats").innerHTML = stats.map((stat) => `
    <button class="stat" data-page="${stat.page}">
      <span class="stat-icon ${stat.color}">${icon(stat.icon)}</span>
      <span>
        <strong>${stat.value}</strong>
        <b>${stat.label}</b>
        <small>${stat.note}</small>
      </span>
      ${icon("arrow")}
    </button>
  `).join("");
}

// JOB CARDS
function companyLogo(job) {
  if (job.logo === "microsoft") {
    return `
      <span class="company-logo microsoft" aria-hidden="true">
        <i></i><i></i><i></i><i></i>
      </span>
    `;
  }

  return `
    <span class="company-logo ${job.logo}" aria-hidden="true">
      ${job.letter}
    </span>
  `;
}

function jobCard(job) {
  const saved = state.saved.has(job.id);
  const applied = state.applications.has(job.id);

  return `
    <article class="job-card">
      <div class="job-top">
        ${companyLogo(job)}
        <div class="job-title">
          <h3>${job.title}</h3>
          <div class="company-line">
            <span>${job.company}</span>
            <span class="new-tag">DEMO LISTING</span>
          </div>
        </div>
        <div class="match">
          <strong>${job.match}</strong><small>%</small>
          <span>SAMPLE MATCH</span>
        </div>
      </div>

      <div class="job-meta">
        <span>${icon("pin")}${job.location}</span>
        <span>${icon("clock")}${job.type}</span>
        <span>${icon("money")}${job.salary}</span>
      </div>

      <p class="job-description">${job.description}</p>

      <div class="job-bottom">
        <div class="tags">
          ${job.skills.map((skill) =>
            `<span class="tag">${skill}</span>`
          ).join("")}
        </div>

        <div class="job-actions">
          <button
            class="button ${saved ? "saved" : "outline"}"
            data-save="${job.id}"
            aria-pressed="${saved}"
            aria-label="${saved ? "Unsave" : "Save"} ${job.title}"
          >
            ${icon("heart")}${saved ? "Saved" : "Save"}
          </button>

          <button class="button primary" data-details="${job.id}">
            ${applied ? "View application" : "View details"}
            ${icon("arrow")}
          </button>
        </div>
      </div>
    </article>
  `;
}

function emptyState(title, message) {
  return `
    <div class="empty-state">
      <h3>${title}</h3>
      <p>${message}</p>
    </div>
  `;
}

function filteredJobs() {
  return jobs.filter((job) => {
    const matchesPage =
      state.page === "saved" ? state.saved.has(job.id) :
      state.page === "applications" ? state.applications.has(job.id) :
      true;

    const matchesFilter =
      state.filter === "All" ||
      (state.filter === "Remote" ? job.remote : job.type === state.filter);

    const searchableText = [
      job.title, job.company, job.location, job.type, ...job.skills
    ].join(" ").toLowerCase();

    return matchesPage && matchesFilter &&
      searchableText.includes(state.search.toLowerCase().trim());
  });
}

// OTHER PAGES
function renderCompanies() {
  $("#content").innerHTML = jobs.map((job) => `
    <article class="content-card">
      <div class="job-top">
        ${companyLogo(job)}
        <div>
          <h3>${job.company}</h3>
          <p>Sample opportunity: ${job.title}</p>
        </div>
      </div>
      <button class="button light" data-details="${job.id}"
              style="margin-top:16px">
        View sample role ${icon("arrow")}
      </button>
    </article>
  `).join("");
}

function renderResources() {
  const resources = [
    {
      title: "Build a stronger resume",
      text: "Start with your education, technical skills, and class projects. Describe what you built and the result you achieved.",
      tag: "RESUME CHECKLIST"
    },
    {
      title: "Prepare for your interview",
      text: "Practice explaining a project, solving a technical problem out loud, and describing how you handled a challenge.",
      tag: "INTERVIEW PREPARATION"
    },
    {
      title: "Improve your professional profile",
      text: "Write a short introduction that explains what you are studying, what you can do, and the opportunities you want.",
      tag: "PROFILE GUIDE"
    }
  ];

  $("#content").innerHTML = resources.map((resource) => `
    <article class="content-card">
      <h3>${resource.title}</h3>
      <p>${resource.text}</p>
      <span class="tag">${resource.tag}</span>
    </article>
  `).join("");
}

function renderEvents() {
  $("#content").innerHTML = `
    <article class="content-card">
      <h3>Student Career Fair</h3>
      <p>A sample event for meeting employers and exploring entry-level roles.</p>
      <span class="tag">DEMO EVENT: DATE TO BE ANNOUNCED</span>
    </article>
    <article class="content-card">
      <h3>Resume Review Workshop</h3>
      <p>A sample workshop for reviewing resume structure and highlighting your projects.</p>
      <span class="tag">DEMO EVENT: DATE TO BE ANNOUNCED</span>
    </article>
  `;
}

function renderSettings() {
  const profile = state.profile;

  $("#content").innerHTML = `
    <section class="content-card">
      <h3>Edit your profile</h3>
      <p style="margin-bottom:20px">
        Changes stay in this browser session.
      </p>

      <form id="profile-form" class="settings-form">
        <label>
          Full name
          <input name="name" value="${escapeHTML(profile.name)}"
                 maxlength="80" required>
        </label>
        <label>
          Email address
          <input name="email" type="email"
                 value="${escapeHTML(profile.email)}" required>
        </label>
        <label>
          Skills
          <input name="skills" value="${escapeHTML(profile.skills)}"
                 placeholder="Python, Java, networking">
        </label>
        <label>
          Short bio
          <textarea name="bio" rows="4"
                    maxlength="600">${escapeHTML(profile.bio)}</textarea>
        </label>
        <label class="checkbox-row">
          <input name="education" type="checkbox"
                 ${profile.education ? "checked" : ""}>
          I have added my education
        </label>
        <button class="button primary" type="submit">
          Save profile ${icon("arrow")}
        </button>
      </form>
    </section>
  `;
}

// PAGE NAVIGATION
function render() {
  const firstName = state.profile.name.trim().split(/\s+/)[0];

  const pages = {
    dashboard: {
      title: `Welcome back, ${firstName}.`,
      subtitle: "Discover opportunities, build your skills, and take your next step.",
      section: "Recommended for you",
      detail: "Sample opportunities to explore your interface."
    },
    jobs: {
      title: "Explore opportunities",
      subtitle: "Find a role that fits your interests and skills.",
      section: "All opportunities",
      detail: "Browse the sample job listings below."
    },
    applications: {
      title: "My applications",
      subtitle: "Keep track of the roles you have tried applying to.",
      section: "Your demo applications",
      detail: "These applications are recorded locally for demonstration."
    },
    saved: {
      title: "Saved jobs",
      subtitle: "Your next opportunity could be on this list.",
      section: "Your shortlist",
      detail: "Jobs you have saved during this session."
    },
    companies: {
      title: "Explore companies",
      subtitle: "Get to know the companies in this sample workspace.",
      section: "Featured companies",
      detail: "Company names are used for interface demonstration."
    },
    resources: {
      title: "Career resources",
      subtitle: "A little preparation can make your next step easier.",
      section: "Tools for your next move",
      detail: "Simple tips to help you prepare."
    },
    events: {
      title: "Career events",
      subtitle: "Connect, learn, and prepare for what comes next.",
      section: "Upcoming opportunities",
      detail: "Placeholder events for your project demonstration."
    },
    settings: {
      title: "Profile & Settings",
      subtitle: "Tell your story and update your information.",
      section: "Your information",
      detail: "Manage your sample student profile."
    }
  };

  const page = pages[state.page];
  const isJobPage = [
    "dashboard", "jobs", "saved", "applications"
  ].includes(state.page);

  $("#page-title").textContent = page.title;
  $("#page-subtitle").textContent = page.subtitle;
  $("#section-title").textContent = page.section;
  $("#section-subtitle").textContent = page.detail;
  $("#filters").hidden = !isJobPage;
  $("#view-all").hidden = state.page !== "dashboard";
  $("#results-footer").hidden = !isJobPage;
  $("#search").disabled = !isJobPage;

  document.querySelectorAll("#navigation .nav-item").forEach((button) => {
    const active = button.dataset.page === state.page;
    button.classList.toggle("active", active);

    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });

  document.querySelectorAll("[data-filter]").forEach((button) => {
    const active = button.dataset.filter === state.filter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });

  renderStats();
  renderProfile();

  if (isJobPage) {
    const results = filteredJobs();

    const emptyMessages = {
      saved: [
        "No saved jobs found",
        "Save a job using its Save button, or adjust your search and filters."
      ],
      applications: [
        "No demo applications found",
        "Open a job and select Apply in demo, or adjust your filters."
      ]
    };

    const [title, message] = emptyMessages[state.page] || [
      "No matching opportunities",
      "Try another keyword or select a different filter."
    ];

    $("#content").innerHTML = results.length
      ? results.map(jobCard).join("")
      : emptyState(title, message);

    $("#results-footer").textContent =
      `${results.length} sample ${
        results.length === 1 ? "opportunity" : "opportunities"
      }. Demo data`;
  } else if (state.page === "companies") {
    renderCompanies();
  } else if (state.page === "resources") {
    renderResources();
  } else if (state.page === "events") {
    renderEvents();
  } else if (state.page === "settings") {
    renderSettings();
  }
}

function navigate(page) {
  state.page = page;
  state.filter = "All";
  state.search = "";
  $("#search").value = "";
  render();
  $("#page-title").focus();
}

// JOB DETAILS
function showDetails(id) {
  const job = jobs.find((item) => item.id === id);
  if (!job) return;

  const applied = state.applications.has(id);

  $("#dialog-content").innerHTML = `
    <h2>${job.title}</h2>
    <p>${job.company}, ${job.location}</p>

    <div class="job-meta">
      <span>${icon("clock")}${job.type}</span>
      <span>${icon("money")}${job.salary}</span>
    </div>

    <p>${job.description}</p>
    <h3>What you will bring</h3>
    <ul>
      ${job.requirements.map((requirement) =>
        `<li>${requirement}</li>`
      ).join("")}
    </ul>

    <h3>Skills</h3>
    <div class="tags">
      ${job.skills.map((skill) =>
        `<span class="tag">${skill}</span>`
      ).join("")}
    </div>

    <p style="margin-top:20px">
      This is a fictional listing. Applying here does not send
      information to an employer.
    </p>

    <button class="button primary" data-apply="${id}"
            ${applied ? "disabled" : ""}>
      ${applied ? "Demo application recorded" : "Apply in demo"}
      ${icon("arrow")}
    </button>
  `;

  $("#details-dialog").setAttribute("aria-label", job.title);
  $("#details-dialog").showModal();
}

// BUTTON EVENTS
document.addEventListener("click", (event) => {
  const pageButton = event.target.closest("[data-page]");
  if (pageButton) {
    navigate(pageButton.dataset.page);
    return;
  }

  const filterButton = event.target.closest("[data-filter]");
  if (filterButton) {
    state.filter = filterButton.dataset.filter;
    render();
    return;
  }

  const saveButton = event.target.closest("[data-save]");
  if (saveButton) {
    const id = Number(saveButton.dataset.save);
    const wasSaved = state.saved.has(id);

    if (wasSaved) state.saved.delete(id);
    else state.saved.add(id);

    render();

    const replacement = document.querySelector(`[data-save="${id}"]`);
    if (replacement) replacement.focus();
    else $("#page-title").focus();

    notify(wasSaved ? "Job removed from saved jobs." : "Job saved.");
    return;
  }

  const detailsButton = event.target.closest("[data-details]");
  if (detailsButton) {
    showDetails(Number(detailsButton.dataset.details));
    return;
  }

  const applyButton = event.target.closest("[data-apply]");
  if (applyButton) {
    const id = Number(applyButton.dataset.apply);
    state.applications.add(id);
    $("#details-dialog").close();
    render();

    const replacement = document.querySelector(`[data-details="${id}"]`);
    if (replacement) replacement.focus();

    notify("Demo application recorded. Nothing was sent to an employer.");
  }
});

$("#search").addEventListener("input", (event) => {
  state.search = event.target.value;
  render();
});

$("#close-dialog").addEventListener("click", () => {
  $("#details-dialog").close();
});

$("#notifications").addEventListener("click", () => {
  notify("You are all caught up. No new notifications.");
});

// PROFILE FORM
document.addEventListener("submit", (event) => {
  if (event.target.id !== "profile-form") return;
  event.preventDefault();

  const form = event.target;
  const nameInput = form.elements.namedItem("name");
  nameInput.setCustomValidity("");

  if (!nameInput.value.trim()) {
    nameInput.setCustomValidity("Please enter your name.");
    nameInput.reportValidity();
    return;
  }

  const data = new FormData(form);

  state.profile = {
    name: String(data.get("name")).trim(),
    email: String(data.get("email")).trim(),
    skills: String(data.get("skills")).trim(),
    bio: String(data.get("bio")).trim(),
    education: data.get("education") === "on"
  };

  render();
  $("#profile-form").querySelector('[name="name"]').focus();
  notify("Profile updated for this session.");
});

document.addEventListener("input", (event) => {
  if (event.target.matches('#profile-form [name="name"]')) {
    event.target.setCustomValidity("");
  }
});

// RESUME FILE SELECTION
function selectResume(file) {
  if (!file) return;

  if (!/\.(pdf|doc|docx)$/i.test(file.name)) {
    $("#resume").value = "";
    notify("Please select a PDF, DOC, or DOCX file.");
    return;
  }

  if (file.size > 5 * 1024 * 1024) {
    $("#resume").value = "";
    notify("Please select a file smaller than or equal to 5 MB.");
    return;
  }

  state.resume = file;
  $("#resume-label").textContent = file.name;
  renderProfile();
  notify("Resume selected for this session. No file was uploaded.");
}

$("#resume").addEventListener("change", (event) => {
  selectResume(event.target.files[0]);
});

const uploadZone = $("#upload-zone");

["dragenter", "dragover"].forEach((eventName) => {
  uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    uploadZone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    uploadZone.classList.remove("dragging");
  });
});

uploadZone.addEventListener("drop", (event) => {
  const files = event.dataTransfer.files;

  if (files.length !== 1) {
    notify("Please drop one resume file at a time.");
    return;
  }

  selectResume(files[0]);
});

// SEARCH KEYBOARD SHORTCUT
document.addEventListener("keydown", (event) => {
  const editing = event.target.closest(
    "input, textarea, select, [contenteditable]"
  );

  if (
    event.key === "/" &&
    !editing &&
    !$("#details-dialog").open &&
    !$("#search").disabled
  ) {
    event.preventDefault();
    $("#search").focus();
  }
});

// START
renderIcons();
render();
