import { NextRequest, NextResponse } from "next/server";

const API_BACKEND = process.env.API_URL || "http://127.0.0.1:8000";

export async function GET(request: NextRequest) {
  const authToken = request.cookies.get("finn_auth_token")?.value;

  if (!authToken) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  try {
    const res = await fetch(`${API_BACKEND}/api/auth/me`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (!res.ok) {
      return NextResponse.json({ error: "Failed to fetch user" }, { status: res.status });
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
}
