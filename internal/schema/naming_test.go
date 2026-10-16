package schema

import "testing"

func TestIsValidIdentifier(t *testing.T) {
	valid := []string{"id", "user_id", "MediaAsset", "_private", "extra_metadata"}
	for _, name := range valid {
		if !IsValidIdentifier(name) {
			t.Errorf("%q 应当是合法标识符", name)
		}
	}

	invalid := []string{
		"", "1bad", "has space", "x = 1; import os", "class", "for", "None",
		"__import__('os')",
	}
	for _, name := range invalid {
		if IsValidIdentifier(name) {
			t.Errorf("%q 不应当是合法标识符", name)
		}
	}
}

func TestToSnakeCase(t *testing.T) {
	// 期望值取自 Python 版权威实现的实测输出，而不是凭印象写的：
	//   MediaAsset -> media_asset, User -> user, VIPPlan -> vip_plan,
	//   PostComment -> post_comment, HTTPServer -> http_server, OAuth2Token -> o_auth2_token
	cases := map[string]string{
		"MediaAsset":  "media_asset",
		"User":        "user",
		"VIPPlan":     "vip_plan",
		"PostComment": "post_comment",
		"id":          "id",
		"HTTPServer":  "http_server",
		"OAuth2Token": "o_auth2_token",
		"Blog":        "blog",
	}
	for input, want := range cases {
		if got := ToSnakeCase(input); got != want {
			t.Errorf("ToSnakeCase(%q) = %q, want %q", input, got, want)
		}
	}
}

func TestToTableName(t *testing.T) {
	if got := ToTableName("User", ""); got != "users" {
		t.Errorf("ToTableName(User) = %q, want users", got)
	}
	if got := ToTableName("MediaAsset", ""); got != "media_assets" {
		t.Errorf("ToTableName(MediaAsset) = %q, want media_assets", got)
	}
	// 显式配置优先
	if got := ToTableName("User", "sys_users"); got != "sys_users" {
		t.Errorf("显式表名应当优先，得到 %q", got)
	}
	// 已以 s 结尾则不重复加
	if got := ToTableName("Tags", ""); got != "tags" {
		t.Errorf("ToTableName(Tags) = %q, want tags", got)
	}
}

func TestReservedNames(t *testing.T) {
	for _, name := range []string{"metadata", "registry", "query", "session"} {
		if _, ok := ReservedNames[name]; !ok {
			t.Errorf("%q 应当在保留名里", name)
		}
	}
}
