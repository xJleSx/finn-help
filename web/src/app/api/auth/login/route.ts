import { NextRequest, NextResponse } from "next/server";

const API_BACKEND = process.env.API_URL || "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  const body = await request.json();

  try {
    const res = await fetch(`${API_BACKEND}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "Login failed");
      return NextResponse.json({ error: text }, { status: res.status });
    }

    const data = await res.json();

    const response = NextResponse.json({
      user_id: data.user_id,
      username: data.username,
    });

    const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";

    response.headers.append(
      "Set-Cookie",
      `finn_auth_token=${data.access_token}; Path=/; HttpOnly; SameSite=Lax${secure}; Max-Age=86400`
    );
    response.headers.append(
      "Set-Cookie",
      `finn_refresh_token=${data.refresh_token}; Path=/api/auth; HttpOnly; SameSite=Lax${secure}; Max-Age=2592000`
    );

    return response;
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
