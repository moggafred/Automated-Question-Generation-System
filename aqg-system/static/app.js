document.addEventListener("DOMContentLoaded", () => {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("fileInput");
    const fileProgressText = document.getElementById("fileProgressText");
    const generationForm = document.getElementById("generationForm");

    const emptyState = document.getElementById("emptyState");
    const loadingState = document.getElementById("loadingState");
    const quizResultWrapper = document.getElementById("quizResultWrapper");
    const questionsContainer = document.getElementById("questionsContainer");
    const renderedQuizTitle = document.getElementById("renderedQuizTitle");

    const themeToggle = document.getElementById("themeToggle");
    const themeIcon = document.getElementById("themeIcon");

    let currentSelectedFile = null;

    // --- Theme engine (persists across sessions, honors OS preference) ---
    function setTheme(isDark) {
        document.documentElement.classList.toggle("dark", isDark);
        themeIcon.className = isDark ? "fa-solid fa-sun text-sm" : "fa-solid fa-moon text-sm";
        localStorage.setItem("aqg-theme", isDark ? "dark" : "light");
    }

    const savedTheme = localStorage.getItem("aqg-theme");
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    setTheme(savedTheme ? savedTheme === "dark" : prefersDark);

    themeToggle.addEventListener("click", () => {
        setTheme(!document.documentElement.classList.contains("dark"));
    });

    // Click trigger setup
    dropzone.addEventListener("click", () => fileInput.click());

    // File input selection sync tracking
    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFileSelection(e.target.files[0]);
        }
    });

    // Drag-Over Bindings configuration loops
    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.replace("border-slate-300", "border-blue-500");
        dropzone.classList.replace("dark:border-slate-700", "dark:border-blue-500");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.replace("border-blue-500", "border-slate-300");
        dropzone.classList.replace("dark:border-blue-500", "dark:border-slate-700");
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.replace("border-blue-500", "border-slate-300");
        dropzone.classList.replace("dark:border-blue-500", "dark:border-slate-700");
        if (e.dataTransfer.files.length > 0) {
            handleFileSelection(e.dataTransfer.files[0]);
        }
    });

    function handleFileSelection(file) {
        currentSelectedFile = file;
        fileProgressText.innerHTML = `Selected file: <strong class="text-blue-600">${file.name}</strong>`;
    }

    // Dynamic Network Post Request orchestration loop
    generationForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!currentSelectedFile) {
            alert("Application runtime missing required dependency: Please upload a valid source context file before submission.");
            return;
        }

        // Toggle visibility interfaces safely
        emptyState.classList.add("hidden");
        quizResultWrapper.classList.add("hidden");
        loadingState.classList.remove("hidden");

        const formData = new FormData();
        formData.append("file", currentSelectedFile);
        formData.append("type", document.getElementById("questionType").value);
        formData.append("count", document.getElementById("questionCount").value);
        formData.append("topic", document.getElementById("focusTopic").value.trim());

        try {
            const response = await fetch("/api/v1/generate", {
                method: "POST",
                body: formData
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || "Upstream internal operational execution exception.");
            }

            const data = await response.json();
            renderQuizResults(data);
        } catch (error) {
            alert(`Execution Lifecycle Aborted: ${error.message}`);
            emptyState.classList.remove("hidden");
        } finally {
            loadingState.classList.add("hidden");
        }
    });

    function renderQuizResults(data) {
        renderedQuizTitle.textContent = data.quiz_title || "Generated Assessment Suite";
        questionsContainer.innerHTML = "";

        if (!data.questions || data.questions.length === 0) {
            questionsContainer.innerHTML = `<div class="p-4 bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-500/20 rounded-xl text-sm">No valid evaluation metrics parsed. Try adapting text contexts metrics.</div>`;
        } else {
            data.questions.forEach((q) => {
                const card = document.createElement("div");
                card.className = "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-xs space-y-3";

                let optionsHTML = "";
                if (q.type === "multiple-choice" && q.options) {
                    optionsHTML = `<div class="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">`;
                    q.options.forEach(opt => {
                        const isCorrect = opt === q.correct_answer;
                        optionsHTML += `
                            <div class="border border-slate-200 dark:border-slate-700 rounded-xl p-3 text-sm flex items-center justify-between bg-slate-50 dark:bg-slate-800 hover:bg-slate-100/50 dark:hover:bg-slate-700/50 transition cursor-pointer">
                                <span>${opt}</span>
                                ${isCorrect ? '<span class="text-[10px] bg-emerald-100 dark:bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 px-1.5 py-0.5 rounded font-bold uppercase tracking-wide">Correct</span>' : ''}
                            </div>`;
                    });
                    optionsHTML += `</div>`;
                } else if (q.type === "short-answer") {
                    optionsHTML = `
                        <div class="mt-2 p-3 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 border-dashed rounded-xl">
                            <span class="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase block mb-1">Expected Sample Target Key Answer:</span>
                            <p class="text-sm font-semibold text-slate-800 dark:text-slate-100">${q.correct_answer}</p>
                        </div>`;
                } else if (q.type === "fill-in-the-blank") {
                    optionsHTML = `
                        <div class="mt-2 p-3 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 border-dashed rounded-xl">
                            <span class="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase block mb-1">Missing Anchor Key Value Solution:</span>
                            <p class="text-sm font-mono font-bold text-blue-600 dark:text-blue-400">${q.correct_answer}</p>
                        </div>`;
                }

                card.innerHTML = `
                    <div class="flex justify-between items-start gap-4">
                        <h4 class="text-sm font-bold text-slate-900 dark:text-slate-100 flex gap-2">
                            <span class="bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 h-5 w-5 rounded-full flex items-center justify-center text-xs shrink-0">${q.id}</span>
                            ${q.question}
                        </h4>
                        <span class="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md shrink-0 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">${q.type}</span>
                    </div>
                    ${optionsHTML}
                    <div class="bg-blue-50/50 dark:bg-blue-500/10 border border-blue-100 dark:border-blue-500/20 rounded-xl p-3 text-xs text-blue-800 dark:text-blue-200 mt-2">
                        <strong class="font-bold flex items-center gap-1 mb-0.5"><i class="fa-solid fa-circle-info"></i> Psychometric Validation Context Metrics:</strong>
                        ${q.explanation}
                    </div>
                `;
                questionsContainer.appendChild(card);
            });
        }

        quizResultWrapper.classList.remove("hidden");
    }
});