import { useState } from "react";
import api from "../api";

const starterPrompts = [
  "topper",
  "who failed",
  "result of Abir",
  "students with A+",
  "students with A+ but failed in another subject",
  "inconsistent performers",
  "GP = 0 but also A grades",
  "average SGPA",
  "top 5 students",
];

function ResultTable({ students }) {
  const normalizedStudents = Array.isArray(students) ? students : [];

  if (!normalizedStudents.length) {
    return null;
  }

  return (
    <div className="mt-3 overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-3 text-left font-semibold text-slate-500">USN</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-500">Name</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-500">SGPA</th>
              <th className="px-4 py-3 text-left font-semibold text-slate-500">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {normalizedStudents.map((student) => (
              <tr key={`chat-${student.usn}`}>
                <td className="px-4 py-3 text-slate-700">{student.usn}</td>
                <td className="px-4 py-3 text-slate-700">{student.name}</td>
                <td className="px-4 py-3 text-slate-700">{Number(student.sgpa).toFixed(2)}</td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${
                      student.pass_fail === "FAIL"
                        ? "bg-rose-100 text-rose-700"
                        : "bg-emerald-100 text-emerald-700"
                    }`}
                  >
                    {student.pass_fail}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function QueryChat() {
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      answer: "Ask about topper, failures, student results, prefixes, grades, or top ranks.",
      students: [],
      suggestions: starterPrompts,
    },
  ]);
  const [loading, setLoading] = useState(false);

  const buildHistoryPayload = (currentMessages) =>
    currentMessages
      .slice(-8)
      .map((message) => ({
        role: message.role,
        content: message.answer || "",
        student_usns: (message.students || []).map((student) => student.usn),
      }));

  const fetchQueryResponse = async (trimmed, history) => {
    try {
      return await api.post("/analytics/query", { query: trimmed, history });
    } catch (error) {
      if (error.response?.status === 404) {
        return api.post("/analytics", { query: trimmed, history });
      }
      throw error;
    }
  };

  const submitQuery = async (nextQuery) => {
    const trimmed = nextQuery.trim();
    if (!trimmed) {
      return;
    }

    const nextUserMessage = { role: "user", answer: trimmed, students: [] };
    const nextMessages = [...messages, nextUserMessage];
    const history = buildHistoryPayload(nextMessages);
    setMessages(nextMessages);
    setQuery("");
    setLoading(true);

    try {
      const response = await fetchQueryResponse(trimmed, history);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          answer: response.data.answer || "No answer was returned.",
          students: Array.isArray(response.data.students) ? response.data.students : [],
          meta: response.data.meta || {},
          suggestions: Array.isArray(response.data.suggestions) ? response.data.suggestions : starterPrompts,
        },
      ]);
    } catch (error) {
      const message =
        error.response?.status === 404
          ? "The query service is not available on the backend. Restart the API server and try again."
          : error.response?.data?.detail || "The query could not be completed.";
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          answer: message,
          students: [],
          suggestions: starterPrompts,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    await submitQuery(query);
  };

  return (
    <section className="rounded-[2rem] bg-white p-6 shadow-soft">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-teal-700">Natural Language Querying</p>
          <h3 className="mt-2 text-2xl font-semibold text-slate-900">Chat With The Uploaded Results</h3>
          <p className="mt-2 max-w-2xl text-sm text-slate-600">
            Ask follow-up questions naturally. The assistant retrieves relevant student/result chunks from the uploaded dataset and answers from that context.
          </p>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {starterPrompts.map((prompt) => (
          <button
            key={prompt}
            type="button"
            onClick={() => submitQuery(prompt)}
            className="rounded-full border border-teal-200 bg-teal-50 px-3 py-2 text-sm font-medium text-teal-800 transition hover:border-teal-300 hover:bg-teal-100"
          >
            {prompt}
          </button>
        ))}
      </div>

      <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        Try follow-ups like `What about his grades?`, `Show only failed students`, or `Summarize this class`.
      </div>

      <div className="mt-6 space-y-4">
        {messages.map((message, index) => (
          <div
            key={`${message.role}-${index}`}
            className={`rounded-[1.75rem] px-5 py-4 ${
              message.role === "user"
                ? "ml-auto max-w-2xl bg-slate-900 text-white"
                : "mr-auto max-w-4xl border border-slate-200 bg-slate-50 text-slate-900"
            }`}
          >
            <p className="text-xs font-semibold uppercase tracking-[0.2em] opacity-70">
              {message.role === "user" ? "You" : "Assistant"}
            </p>
            <p className="mt-2 text-sm leading-6">{message.answer}</p>
            {message.students?.length ? <ResultTable students={message.students} /> : null}
            {message.meta?.citations?.length ? (
              <p className="mt-3 text-xs text-slate-500">Sources: {message.meta.citations.join(" | ")}</p>
            ) : null}
            {message.suggestions?.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {message.suggestions.map((suggestion) => (
                  <button
                    key={`${index}-${suggestion}`}
                    type="button"
                    onClick={() => submitQuery(suggestion)}
                    className="rounded-full bg-white px-3 py-1.5 text-xs font-medium text-slate-700 ring-1 ring-slate-200 transition hover:bg-slate-100"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ))}

        {loading ? (
          <div className="mr-auto max-w-xl rounded-[1.75rem] border border-slate-200 bg-slate-50 px-5 py-4 text-sm text-slate-600">
            Interpreting the query and composing the answer...
          </div>
        ) : null}
      </div>

      <form onSubmit={handleSubmit} className="mt-6 rounded-[1.75rem] border border-slate-200 bg-slate-950 p-3 shadow-lg">
        <div className="flex flex-col gap-3 md:flex-row">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask anything about the uploaded results..."
            className="min-h-14 flex-1 rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-400 focus:border-teal-400"
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded-2xl bg-teal-500 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-teal-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? "Thinking..." : "Send Query"}
          </button>
        </div>
      </form>
    </section>
  );
}
