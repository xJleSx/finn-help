import { NextRequest, NextResponse } from "next/server";

const API_BACKEND = process.env.API_URL || "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get("finn_refresh_token")?.value;

  if (refreshToken) {
    try {
      await fetch(`${API_BACKEND}/api/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // ignore backend errors during logout
    }
  }

  const response = NextResponse.json({ status: "ok" });

  response.headers.append(
    "Set-Cookie",
    "finn_auth_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
  );
  response.headers.append(
    "Set-Cookie",
    "finn_refresh_token=; Path=/api/auth; HttpOnly; SameSite=Lax; Max-Age=0"
  );
  response.headers.append(
    "Set-Cookie",
    "finn_auth_user=; Path=/; SameSite=Lax; Max-Age=0"
  );

  return response;
}
