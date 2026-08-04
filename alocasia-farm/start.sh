#!/usr/bin/env bash
# 알로카시아 스마트팜 실행 (맥/리눅스)
cd "$(dirname "$0")"

# 키는 farm_env.sh 에 따로 (깃에 안 올라감)
[ -f farm_env.sh ] && source farm_env.sh || \
  echo "[알림] farm_env.sh 가 없어 데모 모드로 켭니다."

PORT=8123
python3 -m uvicorn main:app --port "$PORT" &
SRV=$!
sleep 3
(command -v open >/dev/null && open "http://127.0.0.1:$PORT") || \
  (command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT")
echo "끄려면 Ctrl+C. 식물 정보는 farm.db 에 남습니다."
wait $SRV
