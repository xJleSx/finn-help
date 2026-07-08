import { NextRequest, NextResponse } from "next/server";

const API_BACKEND = process.env.API_URL || "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get("finn_refresh_token")?.value;

  if (!refreshToken) {
    return NextResponse.json({ error: "No refresh token" }, { status: 401 });
  }

  try {
    const res = await fetch(`${API_BACKEND}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!res.ok) {
      const response = NextResponse.json({ error: "Token refresh failed" }, { status: 401 });
      response.headers.append(
        "Set-Cookie",
        "finn_auth_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
      );
      response.headers.append(
        "Set-Cookie",
        "finn_refresh_token=; Path=/api/auth; HttpOnly; SameSite=Lax; Max-Age=0"
      );
      return response;
    }

    const data = await res.json();
    const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";

    const response = NextResponse.json({ status: "ok" });

    response.headers.append(
      "Set-Cookie",
      `finn_auth_token=${data.access_token}; Path=/; HttpOnly; SameSite=Lax${secure}; Max-Age=86400`
    );

    return response;
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
