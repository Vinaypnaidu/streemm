type HelloResponse = { message: string };

export default async function Page() {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  let message = "(API not running)";

  try {
    const res = await fetch(`${base}/hello`, { cache: "no-store" });
    if (res.ok) {
      const data = (await res.json()) as HelloResponse;
      message = data.message ?? message;
    }
  } catch {
    // keep default message
  }

  return (
    <main>
      <h1>web hello</h1>
      <p>
        API says: <strong>{message}</strong>
      </p>
      <p>
        Health:{" "}
        <a href={`${base}/healthz`} target="_blank" rel="noreferrer">
          /healthz
        </a>
      </p>
    </main>
  );
}
