# Annotation tool: circle problems on a render and leave a note for the agents.
#
#   ruby tools/annotate/serve.rb [port]      # then open http://127.0.0.1:8790
#
# Serves index.html from this folder and the PNGs in renders/, and saves the
# marks drawn on a render to renders/notes/<image>.json, which is where agents
# read them. Listens on 127.0.0.1 only (a container reaches it as
# host.docker.internal:8790). Standard library only.
#
# Each mark carries a thread. Anyone adds a message to it, optionally marking
# the mark ready for review (agents) or sending it back (the owner):
#
#   curl -X POST "http://host.docker.internal:8790/api/thread?image=hand3d_live.png" \
#        -d '{"n": 5, "by": "raj-claude", "text": "boulder moved back", "state": "ready"}'
#
# state is optional: "ready", "sent_back", or left out for a plain reply. A
# message with a state also sets the mark's review to {state, by, note, at}.
# /api/review is the same call with state defaulting to "ready". The page's own
# saves never change a thread or a review, so the owner's autosave cannot erase
# an agent's message and an agent cannot touch the owner's notes.

require "fileutils"
require "json"
require "socket"
require "time"
require "uri"

ROOT = File.expand_path("../..", __dir__)
RENDERS = File.join(ROOT, "renders")
NOTES = File.join(RENDERS, "notes")
INDEX = File.join(__dir__, "index.html")
PORT = Integer(ARGV[0] || 8790)
IMAGE = /\A[\w.-]+\.png\z/
MAX_BODY = 1_000_000
REVIEW_STATES = %w[ready sent_back].freeze
LOCK = Mutex.new

def reply(client, status, type, body)
  client.write("HTTP/1.1 #{status}\r\nContent-Type: #{type}\r\nContent-Length: #{body.bytesize}\r\n" \
               "Cache-Control: no-store\r\nConnection: close\r\n\r\n")
  client.write(body)
end

def json(client, value, status = "200 OK")
  reply(client, status, "application/json", JSON.generate(value))
end

# The image a request names, or nil unless it is a plain PNG file name.
def image_param(query)
  name = URI.decode_www_form(query.to_s).to_h["image"].to_s
  IMAGE.match?(name) ? name : nil
end

def notes_path(image) = File.join(NOTES, "#{image}.json")

def read_notes(image)
  file = notes_path(image)
  File.file?(file) ? JSON.parse(File.read(file)) : { "image" => image, "marks" => [] }
end

def write_notes(image, data)
  data["image"] = image
  data["saved_at"] = Time.now.iso8601
  FileUtils.mkdir_p(NOTES)
  File.write(notes_path(image), JSON.pretty_generate(data) + "\n")
end

def handle(client)
  request = client.gets or return
  method, target = request.split(" ", 3)
  length = 0
  while (line = client.gets) && line != "\r\n"
    key, value = line.split(":", 2)
    length = value.to_i if key.to_s.downcase == "content-length"
  end
  path, query = target.to_s.split("?", 2)

  if method == "GET" && path == "/"
    reply(client, "200 OK", "text/html; charset=utf-8", File.read(INDEX))
  elsif method == "GET" && path == "/api/renders"
    files = Dir.children(RENDERS).grep(IMAGE).map do |name|
      { name: name, mtime: File.mtime(File.join(RENDERS, name)).to_f }
    end
    json(client, files.sort_by { |f| -f[:mtime] })
  elsif method == "GET" && path.start_with?("/renders/")
    name = path.delete_prefix("/renders/")
    file = File.join(RENDERS, name)
    return json(client, { error: "not found" }, "404 Not Found") unless IMAGE.match?(name) && File.file?(file)
    reply(client, "200 OK", "image/png", File.binread(file))
  elsif path == "/api/notes" && (image = image_param(query))
    if method == "GET"
      json(client, LOCK.synchronize { read_notes(image) })
    elsif method == "POST"
      return json(client, { error: "body too large" }, "413 Payload Too Large") if length > MAX_BODY
      data = JSON.parse(client.read(length))
      return json(client, { error: "marks must be a list" }, "400 Bad Request") unless data["marks"].is_a?(Array)
      LOCK.synchronize do
        # Threads and reviews belong to /api/thread: keep what is on disk.
        disk = read_notes(image)["marks"].to_h { |m| [m["n"], m] }
        data["marks"].each do |m|
          m["review"] = disk.dig(m["n"], "review")
          m["thread"] = disk.dig(m["n"], "thread") || []
        end
        write_notes(image, data)
      end
      json(client, { saved: notes_path(image).delete_prefix("#{ROOT}/") })
    else
      json(client, { error: "method not allowed" }, "405 Method Not Allowed")
    end
  elsif method == "POST" && %w[/api/thread /api/review].include?(path) && (image = image_param(query))
    return json(client, { error: "body too large" }, "413 Payload Too Large") if length > MAX_BODY
    body = JSON.parse(client.read(length))
    state = body.key?("state") ? body["state"] : (path == "/api/review" ? "ready" : nil)
    unless state.nil? || REVIEW_STATES.include?(state)
      return json(client, { error: "state must be one of #{REVIEW_STATES.join(', ')}, or left out" }, "400 Bad Request")
    end
    entry = { "by" => body["by"].to_s, "text" => (body["text"] || body["note"]).to_s, "state" => state, "at" => Time.now.iso8601 }
    mark = LOCK.synchronize do
      data = read_notes(image)
      found = data["marks"].find { |m| m["n"] == body["n"].to_i }
      next nil unless found
      (found["thread"] ||= []) << entry
      found["review"] = { "state" => state, "by" => entry["by"], "note" => entry["text"], "at" => entry["at"] } if state
      write_notes(image, data)
      found
    end
    return json(client, { error: "no mark #{body['n'].inspect} on #{image}" }, "404 Not Found") unless mark
    json(client, { entry: entry, review: mark["review"], thread: mark["thread"] })
  else
    json(client, { error: "not found" }, "404 Not Found")
  end
rescue JSON::ParserError
  json(client, { error: "body is not JSON" }, "400 Bad Request")
end

server = TCPServer.new("127.0.0.1", PORT)
puts "annotate: http://127.0.0.1:#{PORT}  (renders: #{RENDERS}, notes: #{NOTES})"
loop do
  client = server.accept
  Thread.new(client) do |c|
    handle(c)
  rescue StandardError => e
    warn "annotate: #{e.class}: #{e.message}"
  ensure
    c.close
  end
end
