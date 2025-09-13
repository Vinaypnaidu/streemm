type HelloResponse = { message: string };

// export default async function Page() {
//   const internalBase = process.env.API_BASE_URL ?? "http://api:8000";
//   const publicBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default async function Page() {
    const internalBase = process.env.API_BASE_URL ?? "http://localhost:8000";
    const publicBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  let message = "(API not running)";

  try {
    const res = await fetch(`${internalBase}/hello`, { cache: "no-store" });
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
        <a href={`${publicBase}/healthz`} target="_blank" rel="noreferrer">
          /healthz
        </a>
      </p>
    </main>
  );
}
