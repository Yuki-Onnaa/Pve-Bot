import base64
import csv
import io
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import wraps

import urllib.error
import urllib.request
import discord
from flask import Flask, Response, session, redirect, request, jsonify, render_template_string

from data_store import DATA_FILE, load_data, save_data, data_txn

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

# ── Discord OAuth2 ──
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
# e.g. https://dashboard.sapph.xyz/callback  - must match the Discord dev portal exactly
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "")
# Optional: restrict the dashboard to a single server. Empty = any server you admin.
REQUIRED_GUILD_ID = os.environ.get("GUILD_ID", "").strip()
# Optional: extra allowlist of Discord user IDs, comma separated. Empty = no extra filter.
ALLOWED_USER_IDS = {
    u.strip() for u in os.environ.get("ALLOWED_USER_IDS", "").split(",") if u.strip()
}

# Embedded dashboard logo (base64 so it needs no hosting).
LOGO_SRC = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAQDAwMDAgQDAwMEBAQFBgoGBgUFBgwICQcKDgwPDg4MDQ0PERYTDxAVEQ0NExoTFRcYGRkZDxIbHRsYHRYYGRj/2wBDAQQEBAYFBgsGBgsYEA0QGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBgYGBj/wAARCADAAMADASIAAhEBAxEB/8QAHQAAAQQDAQEAAAAAAAAAAAAAAAQFBggBAwcCCf/EADwQAAEDAwMCBQMCBAMIAwEAAAECAwQABREGEiEHMQgTIkFRFGFxMpEVI0KBJKHBFhgzQ1Ji4fAXY7HR/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKLzYFvYdwXy2BjKQdxNNb4YDv8Ahyso/wC8YNS2VFZe52oUs++BSH+DtPElzLSuxI5BoI6FKT2JH4r2l95P6XFU9u6ebSn0Prz9xmtTNhWlaVuujbnsBz3oG9la3pKPOfCR8kU+rZg7Eubw4M8AYwKUKt0LhIZSo+5oVCgREFYQhIPJJPag8FCAhJQwE+1aZUbz0bEK8sDuQa3Gdb1tj+ekD7nGaFiOUBxKSrI+e9AwSbe5G9RIWn7Hmki9pV6UFP2JzUmUhpbfqbAAH9RpI80y22p9JQMcA4oGMgjuCPzRg4ziljqXH2vMQgKT/wBRoag729y1EEnAFAiopTJhuxxuUPTnGc1pS0VJ3BSB9iaDxRQRg4ooCiiigKKKKAooooCiiigkM6+MIJbhgrI/5h7UiZnvSXgJM8x09vSmmv3ooJ2hUURW8SW3CE/q3Dnj81rc8wuDyg2tJ981CMn5rciVJbSEtvuJA9gqglNyUhtCVpkqbJ4wBkGhTSpMVKQTtUOT96jq7rMWEhSknb24pwTfEtwwlSNzo7jGBQKxYYjYC3FqUvOe/FKlQI/04CXVAbsD7c0xO3yS6ztLbY+4BrDd6cQyEKaCj+aB3kRI7Ufcp4ggYKgO/wCaQuyLctgMB8qB5ORgU1SJr0jhSiE/GaT0Eh8y3sMJabcaO770pdaZ8kKQpIycE151LetKyrZZoOldOO24w42JkyU95z05843LPGEJHZKR7c9zUcckOuABSzgdgKCQqZZcacBeCSMevgkcfFY0/ojVGtr2bXoyxXG/TEJ3uNwmC4UDPdWOEj81HEuKScg/vU+0t1s6k6J0JP0hpPUSrRa7glSZSYjDaHHdwIOXdu/sSO/FBBZkSRAuL8GW2W5EdxTTqCQdqknBHH3FaaypRUoqUSSeST71igdCzp8aeS4J09V0PqLQjpDKRnG3duyTjnOMe33proooCiiigKKKKAooooFLiYJY3NuPB0n9BSMAfnNJqKKAr2hpx04bbUs/CRmhtwNqyW0L47KFKxdpaWPKb8ttP/YkDNBrZt019zYiOsEd9wxj96cTamYcIuyZKQ7nGwewpvTcZKXCsqCjj+oZxXkz5Sshx1TgPsrkUGt1ScBKFKI/PFaqypRUok+9YoCiiigKKVS24CGYxhyHnVqaCn0uNhAbcyfSk5O4Ywc8d+1JaAooooCiiigKKKKAooooCiiigKKKKB0d0/dGYYkrj+k8kA8gU3rjvt/8RlxHGfUkiugf7Q2ty3GWVpSR/wArIKv7io+/cFXBxSkRpexWAVBQKcfgigjdFOF1Qv6lKw3tbIwjhIP99tN9AUUUUBRRRQFFFFAUUUUBRRRQFFKl224N2pu5uQZKITiy2iSpshtah3SFdiftSWgKKKKAr0EKPYVlCN3OaWMR96aBOlgnkAmtqYx8snnPtxTzEtnmDsCScYp4Y08osbth4Hfj4oIaYpIPBrUWDtJqbuaeUhs5QAMZ/wA6Z37X5YXuA70ChnRkpE5rKwUA+rcB2qaxoDEeImOCNiRjtik0S5xHQlK3W0k+ynAT+ac3HIyGwS+jB7YINBojaTavt3iWqLHDsiW8lhhskjctRwkfue9L9ZaH6RaSectNtl6g1ffggNuuxNkW2NPdlhC8KcdCT74SDjvisIS4hxl9p5xpxB3oWhW1Q4x3H2NAaHpOeaDmM3SFxaYC48cL55CVZNR59h2O8WnkFKx3Brqd2vS7bc2YiYweC++xXI/tUL1Q2l+YZTbSWucKG8c/2oI5RRRQFFFFAUUUUBRRRQb1zJbkBuEuU8qM0orbYUslCFHGSE9gTgZP2rRRRQFZSMmsVtaSCDmg3sMhQ5p9ttv8wBXuab4bKCBuUO9TnTFvacUkk/j9qCR6Q0bMvFwjwrdDelSXVBLbLKCpaz9gKtZpPwY6km2puRf7xDtCnEBX04SXnEkjsrBABH5NdF8I3Ti32vQy9dSWkuTpqlMRipI/ktJOCR91H/IVZigo/q3wZ6mt9sclWC6QrwUJKjHSksuqwP6Qcgn7ZFVU1PoyTap0iFMiuxpLCihxl1JSpKh3BBr7F1WDxddNYFw0k1r6GylubHUmNMIwPMbOdqj9wePwaD5SNuLQ4FNrKT81I7RKU08h5yY0twHgKKiRUaKcVI9MSrBBmB+5ecXOwAGUf3oJdA1MiVMEUoU8r/6xxUoSguNpVgt8Z570wN3WytPIas0Nt99w/paIH7mpIopbjB6RhoYyoEjigi06x6gevIksTWW2xjgJ9R/NbrvpZ6egByUlKcHICByafWbjAltKW1MaKEnBJUBiovc9R3Fq+iHa1szR7pSBx/eggU23xYc1cZxToUk43KAApvfQyhWGnd/yccU9anFweuinpsIMq9yjsaYSCKDFFFFAUUUUBQQQcEYNOumrwxp/VsC9SbRDuyIbyX/opoJZeKTkJWByU57j3o1Lf52qtYXPUlySwmXcZK5TqY7YbbSpRyQlI4SkdgKBqoopRKbhtln6OQ49uaSpzzG9mxf9SRycgfPGfgUCelDSeO9aB3rc3+aB4gt5GT3zzXRNLFCVoGSQB8n4rm0NW3BB4qY2KZ5SUneKD6i+GHUcO59G41nbV/iYClJWjjhJOQf867dXzW6O9VLhoe9tz4L25B4eZUfSsfirr6X69aE1BDa+ouIgSFcFMjCRn3Ofig6lXI/ErcI8Hw6Xpt9YSqUpqO2PcqKweP7A1Lbl1Q0JarUu4TNRw0Mp4zvyScZwB/73qlHiH65I6kXFmFbmDGssAqMdLh/mPLIwXFfAxwB+aCiDMV+SopjsOulKStQbQVYSO5OPb71YTpb4YkdUulj+orbf5Ua62uSpq5WpccecoKSCwllKinKlknlRAqP9LeoqvDh1l1JIdtVt1LJRCkWhJafCmUuFQ9QXghaeMHgg84qa+HTUk/Wfi3f1jqbUc9hh103O4sMNKdEgoO5pvykA5CVJTg44CfvQQO9dCOq+hy7Mvuj7pY4LCUrcmPthSQlRIBVsJ9xj7ZGe9R+62W/S1toj3V1xvGCHDtH9hX0W6t9StT3G1XK1i3NWR9FtcWbVeG232rlFcBBebx6kOgAEIJ4GcgntTOPAixkBMcI5Hfvmg5XG0VOcaWp99wt59SwoBOP3qNzEt2y54t0h1akHlfYH8V2yZEtyZKUvrbTv4KScYP4qMXfRkELVKevLbUQ/pQAEn9/eg5nOuU+cQqQ6onscEjP9qy3aJj8NcnbtbT3UrIpbPNugXJKIhTKYQcnzBSm8XqFNQ15cJtKkjGMnH7UDC3b5b6Atphak/wDUO1eHo7jDnluDB/OaVOTHVN7Eq8v7JPFJVAkgqPf3oPBRhIORUm0C5oeLriNL6ixLjN0+yhbj0K3OeW9JUEnY2F/0gqxk/GajhbGwYVyfaslhQRkkAUDnqubYbprG4T9L2VVls7rpMS3reLymW8YAUs8qPuTTNs9Oc06W3T9zuyCYEYu4rxOtE6Aj/ExXm9p2qKk8A0DbtNG371sUgbQc5PxWNhxmg8hJPvWxCSWzivO301kA7PxQLmFKCefmniBKKEhW7GPao+2o7e+KWNOen9WD7c0HQrTelsAKK8c1MYWrXm2Dtfzgex7cVxtiSpKCd/NLWpyw2QHOKDqszVjjiDmQSfnOf/2oXc7y5JKv5vz71HlTVeWf5px+aQOSCpJHmUHbdIeGs3xGmNVyJ8i72K4zmxPtVkZW9MhRVJ3KcWvGxIBwDzkA59qttZOiuoOnhs966EO2jSboZbbvMO8pD/1zSHCVOefhSt5BxkADHsad9FXqV068Nlm1HaemFzXChWRFwjMwpiEfVOOJKnBICiCFY53bSO+B2rg2t/FppzS/RqBZOitynQ7/ACC3Jk+fGQ5GjpcSS42gqOdyThPIPufeg7R1K1hZLZ0qvutda6UlR7XaA/Bt1vmykOSpD0gltbiADlJSs4C/VhHOAc4+b1t1G3CuCZElM59AJIaEkgDn8VnV+ttUa6ubc/VN1cuEhsubFrAG3esrUAB2G4k49s0xMxH5cpmLGbU686tLbbaBkqUo4AH5JoJXddTQLmkvJdnxV99gIVk4+e9RV+W+vAD7pQDkBSianWv+ivUfpkiyHWGnnoSruyHY6QQspJVt8teOELzj0n5/NRi96T1Jp7UciwXmzTYl0jIDr8NbZLjSSkL3KAzgbSDn2oGRZKhkqyawUHbnPevZQABg1hSDsHxQayn0jn2r0pB28mvflqVtQkZJwABySfine5aV1BZbcxPvVlnwIrr6o6HJLJaKnEhKlIAVg5AUk9vcUDbGXFbG6S2t3nhIO0VItPuvuXNCmLMXoSf1N7ArP5URUZWkBWWydo7Z706rv9yVbGYyZz7Ya/SGyEp/y70HYkWXzmo/0rbcGMUEuMtHYvJ/FRu66P1TGkefbbsX292UR3zvx+/BqIWjWl0tklctwqmPqG3e84o8fini4dSV3GzJZetuJAJ9aHCAn8feg9K0DcJxffuN4hNOIG5ZZAwk/BxioXJs8pqY5HaUmTs53tHIxSdxx9aFEvL9RyRuNagFpRkKKfuOKDyphxAO5Ck47gjGK87fT3peblOMD6Xz8tHvwM/vSMJ9JOaDCAcfq4ragEI4VWvYdvespSdnfjFAoQ4oJOFc/NbEu/y/1EUkGdvespCg2T7UCoO5TjccVq3HaTvNahkg155wcKoLCdOdF+J7qvou4jSd5u03T12Ui0zXZ9zSll0NDcls7ySAnt6R74riF90/edNX96z36A/b57JwuPITtWOSM4+OOD719MoUKyaO6zjRGl5Nh0p/GAZUaNbQAi5NMJDbzbgPEcrVkBQ5OD8coNX9G+kWg7jqaTqN2HCj6hhqX9VqvdKahPFKm0hl4+pW3cFYzkd6D5mKbUAD3r2y7JiS2pMZ5bTzSwttxBwpKgcgg+xpzmWhMbVblkZuUaahuX9Kicyr+U8N+0OJJx6T359qvePBd0z1D4fhcNG3sq1C1C+oTdnJHmNPuIJVhSQdrYVgg4zjAoODdOJXXHq71C0lPurty1RY7VcWZLjNyfSiIVoJOXM9ycHnB966z4ytEa701e43VnT6bQ0xOiuxLnJtMMofY8xAadDrhGFtHO1K1erKsdsY7fG07pS9+HZq823UluharVam4yrtp+WUNokAIyC22CFbcJyFA5BPPNVl8Q/iI1C4Nc9IZoTdmJQhtC4+atP0zqUIVI2oxjatQHpHA5wTmgqldrO9Z5iIj0yFJUWkObob6XkJ3DO0qHG4diPak8eDMmzGYcNh2RIdWENtNIK1LUTgAAckk1sYhyZctqJGaU486tLbaEjlSicAD96vT4e/Dza+ml4tfUTqczIiyXbekwo03LAi3AuqSpKlj0gbQkJznO8/FBHfDX0G0ppnSEnq71xtM+3C2SCuJGnfymW0BHpdfbxvTlfCFds4rmHib6yXLqrq59Fk84aRQ6HWEOsgu+YAMqW5jcEkk4B9sd6uLq216u1K1qjSbzUK8Q1KQhcyfJNtjRGZQUVN+kqU6hpSCAFYI3GnfQXQLQyfDzeNFW3+KIiXl9sTHpDjRkJJCCpLa9vGB2z3GPmg+XcjRmrmNMuagk6auzNpb2b57kVaWRvGUesjHqBGPmmVSDtHPNfRPrMb5L8KuubKbD/tKm0PKRLk3eShtVsaaARHfbSg4U4UgEJGO+fkV88C2raMk596DUUKCO4rBSQjvW0tq8v/AErBQdgNBr2K2d+KNh2jJrZtPl5PavJSfLznig87FFvNYCFbO9btiigc152K8vuaDWEqKDzQEnZ+qtm1W2sBJ8ug1hBKe/FSOdfrVI0TEstv0ja4ElrBkXUOOuyZJH3Uragc8hIGaYAg7aylB8omg1BKjWAlW0mtoQopPNDbTiwUpSVH4AzQW1vOsuterNeyL7aOm9xhPsQTHmQlJVID7jpyXgEgbT7gJ/8ANMUbpV1Z1r0Yu+p9dat1Czp2Ewu4w7e8w7NWpxsqByhSgWUjJ9Rzx7HFdB6deIjr1q12a/096a2qWzHdC5biSsrcbKsIbSpRG5SQSPT8gke1TDQ/W+6XzqvrPSHVq2xLLpeNEkKbYUFqYaTtUVJcdOMhXqKVEc9kig5v4eOhemRrJX/yGpmdNmaZcuseNvSGYCV+kedu7uFJJ2gen3+atr06Y0/oToz9DD05JtSLbAXHj+SlTrcwHss84WVKXu555IHFVWhdf7Zbtf6q1TIYt1utVxbiIRp2ZEU+9JaZaLYe3qH8lak7VBHuO+M5qRf78loa1dCtTmmX16bYmtJXcIqfKkOw0NpwFNEnKw4CSMgFOBQPXTbrTHvXiOt3S52FarBbEF+LLecjFmTJl4O5W1XCNx9IHOBgjBqv3jQiR4HipuECJa2YTbUKMAtKSlcr0/8AFcP9SjjG73AGajFx6z3hrxPXLrFZ7fajcHZLrsdt2KEtgEbUuKRk4c2gEnPck0r01oHqN4m+p2o7nb7lFduLLRuDwuktZCGi5hLSFkEkJycA+woOUR7VeHGDLi2+Y42y2Xy420ohKU91Zx2HHNWk/wB3XWevugOi73ZOoTl3u1zZkTFwVXRTsbIO/blRAaWlAO4AHJGOMZrsXSa7WR3w8w9K6s+mlWmyXeRYv4raipRfQkhKlBONyBlYyOQU8nAFdFs+hul3T61x7FpyRcdOWyWn69xcdXm72lIIKEPkkDzAk52HPIx3FBxXw/6r6qytJMSZNkecdukhNvZvUplC2WY0dClrKw6AFqVzsKTgnd712zX2m5eoNI6ps1rv8i3XOUj64FwrbQqU23ubMYJ2qO1SR2yDwCCKzJYsdj0dE0nb4oa6bsOMhCLhPUCEgkloLJ3MpSvao+Yee3Y1X/rJaurHUR6BZdL6ilSrn5kie8w3JLUdmO6seUGFnCklKQncM45zxzQSHT14R1b8IOsLTrKK1BcgQXn5DVsGJjymVApWorx6i5uBSeOTiqA7VFsHPBFX9u+oLh0Q8KTblrsttXPirkWmXPbbMlSJa207lSs4CgtRIBydpA74NUGUFrTuJ5JzkUGsoUWsZrBQsN5zxXspWG+TXpDTrm1CcKUo4A+/70C6xQ7NLuKkaguz9uhpZWvzY8YyFrWB6UBOQPUeMk4HemwoUEcZI+9K5cCXAfVGk7A4n9QSsKx/cHFJyhW3g0HgJJb7152L8sjNbAlQRx88igoUW+5FBrCFeWcVgIVs4PtW5KFlvv70BpflE7vb/Sg0hCtgOfespQotnn/3Few2rZweaEoVsPqoMNb0KJCwPfOAadLI3EUXXpdxdirAykNoB3fvTXsXgnP+dZS2stnBoPo6/Pt3TPpXHsOhmGISnWXCPIJ8htaNiXZKjuwFJ2knJPJxtJqunS/Td31r1TXc40K433TjlxDxbuZCWpclv1j6pQ4LYIVt+fjg0inwdV6x6p6a0lrKBcrbaXIKp8WzW+SHXXPMUC4p5zjaXFgqPfaCBirk6chWjQMC26fsiUWtUhSIrTY2yVIWr1bnEj9QSMYJ7DPGDQVu6g9Eo93u2qtQdSeosO1aiQHJjfqbTEcSsKU2ltBCV4GwtknnIGOMVVGDDVNusSI55yg86hs+QjcvClAelPueeB81cnxQOwNTajsPTHpzb4N4u9ydVJnLZaQ86wVKASlSgkKZO7conttPNMHRXwgdQbrqpF81PPGkVWt1mbCMmMH0ylBatoyFAAbm+QeSDkUGbZ4XunU3qBpeyW/qK/OQQ5NvTb8UtOhgKw2hLQGULzhCwog5JIpR4iOnuj+hmjLTcemGrJenLzd0OtToZmOfUzIzuFBGANqGkAHlXJ+5zVjL3qzWly1JcdM3jRAXewiNIjNWS7ojuLShfmOOLkKT6QCE8ZztPIwc1ArBE094j9XMacvUdUhnTTjc24XO8xmHJL0pKlAxGHUcORxgE8HKeARmg4Z4etdv6ft8rS+otWPaNh+Y3eoF2klbS3d6QyfLQpJStJTk5P6sY5q12pOnNh0u7ZxpqUw7ZpH+IvK7yDNZbYabLgeQ0snC1KOAUgJ+3FOQVp7VTN0t2pOkryGrOlEG3iVb2zHejJUEpdYTneQnJUEEggHA5rh/iV1JM6Z6MhLY05Bj3fUrTtvSpbzpaaiNp2jymSRgAlKkJUCE7sgZGaDt/UZ5zXGkf9j7HYbddrPqC2eYmJIkfSyX1pUgoS2pXultKgUkFQPfApm6mGzxOmWnNP22zPaUX50aI7d5qSkWRhHrd/xCVYUoBGwpUcL3Ac18/dDxupGreodva0jfJh1EyXJMN5y4eStKz+vYtasblfA/VV+unHQ+6vynbT1d15L1NBsr+bZZbkpC0NIUkBTzwUPWVKJCeTtx8mgr51f8SWjtddGtW6fRbRIuc68Lbtrf0yW0tREkESVrTwpwkHAxn1c1U4pIRntVl+u/S5m+a4mSdCr0HETACYKNP2SYTKfcSTn0kbXHOQTs+cckGq6XC13K1TnLfc4b8SU0cLZkNlC0+/KTyO9Aj8ta0hIwVEgCpLe+nGutORoj190rdIDcuR9JGW+wQHnePQn/AKicjHzmnronCkTPERoqM0EqLl3YSQWA+NufV6D+rjNXa64RbB1s01dJui9QOJtmkGG5bDjzhbjPSkuHeVJWAra2nCCpJ4UrGCRQUr1v0I6ndPdBW3VWqtOOwYE5amlA8rhuA4CH0gfy1KHKfkV1jw5eGGz9VulV/wBb6sutxtlvih1lhaGghIKEpUXkrP6toCkkYxVm06fvnUrp7GsvWq9QItusimZK9MobLbl2QltSWnVu7ysoWrKkhIJyMK54qSaR0q3p3QGn7JpWBKiaLt0dUifEmLcbdfk+cFpbCDy5kFW5PG70fNBRrp/4bF9UuqupNP6T1ZHYsdnloQ3NmtK86SwtX60IAAJSnJIJHtxXLupOhbl026nXnRV0cS9ItsgtB1BBDqCMoXwTjKSDj2zX0rc6bqc6m3bqhbJ920XFuqkmVChFTci4cJDSwP0tlRBKxgqwOSKpr1Y6D3KV4loll0zclrtuqnfOgXa+SkkKdUDvS44knncPTxk5HFBXQJV5eQRWQFeVjPt/pXdPET4cZ/QR6xqXqSPdot1bO0bPLdbdQlJcBT22ZVhJ7n3rhu1wNZzxQeQk+54zzj80sucmLPmqfgWxi2MbQlMdlalgYHcqVySe5pKlKyCTkVhKF+X9v/FB4CV7DzWEBXlEg8VtCV7TXlttew4oLDak1B1Ja61Xe+aDiuuqbYjsOLYjh7hGDtAVkp9QOQOan2gurnUzVep9TXaLBsOnrWzEeblKdiLccS99PtQgEepSgQVe2PevMW7sN25VoZDsRwsbUtRVFDyVleNwWc4Sok57qByabtFSWdFwrnPiRryE3YJdecedQZAWFYWhS8fpPHb9QPGDQSLw06Ev1q6927XOq7zLm3qVFffehkqW9tWNqXX19iDwQnvjB9q6N1YtWq1dUrRqzSd2kC6NXRP1Fv8AqVORUtFG5tHkjhClEH1EgZJyRUPg6hcF1vU+TbJKU3dv6yY2tSmClaUBtvy3GyChO1OCgfb5Nb2dZM7lyZdqTFvc4ktkkobK22wWkjOQCfUQeTxz9g65JvbaoFxvnUTUbNvEyJ5bkW2uFH0+TlamzlSt4SUtkpH9JyMEVHNJ/wAQ1Tp+2XrQt4tCI0S+rcf1I6yBIcYS4f5Qa2jnaoNkn7H2rnzGtnH23dUoaMKdcGFtIi9jHdAKEuIODhR4Xu7HI9q3wtSO6OhWG22hi5yWJShFktMqSpEdTmVOOlJxklZB/wC3k9jigs3K1VatPXJhu9XZpgXOQW2fNc/46wnKEg4x2SogfkioB1ztM7qt0pulk0hbbNero2hUdAlNFQRvCVEsPdg56QfYDgHnim9bqL/q5li82SJcXm4+9pyakGGw4UhO1s8htZCMkEc/0kE4qaaGs86FrlUi72aaxHtynEQ7giXlq4KdwVuqZSMZUQDk9icZNBQ3pz4e9R3DxDWjp9r+SvR4f810KkKKHJaWV4U2woe55IV2wMjNXI6b6b6d6Qu8dCNXaj1dfHHp8Zm7SXHVtKKE8x8KJSpKAnhR43ZOe1PvVXpDaupmsIt51FKMmBbobrEWApaiW5SjnzQUkYUnAHft7HNc/wCp3UPqPp7SDmhNN6S1Q3qCyNQpyLtb48ZthbCT/NUhHICdox5fc57ACg6bFe0hA8Nrt4sFsZvUu1bcPQYyEuuyQ6FkIUlJzhSuSMjg/eqaeLHTUjVfi7jW3RMS4Xi73iDGK07EBor2hAKXBwpIAwpSuxBB7VYnpr1u0dfdIyImqPrW/rlpWuNMiqYXgJ3IAW2R3GVbvjg8VKLbfNA6e1g9elSrM3ebqooRJMNDaklXq3KcGSRhKR7dqClnTroj190j1qs11s+lGzdrTKVLAcdQphtLfBUteduFAqKeckcgV3WPoV20+LC4ai6yaktjenL005IixIE5bMNCUbXWkLaIwpGUHDZwVkbiDUT6ideLvptp3SuizIvd9fvr9wbajrSpqOFekAIQncpGDwCrb2yPambR2rerGmtLMJ1hZU3xi/yWSm6qkNqlQ22lBlxanMKUClKuMDjk5IoLSay6h6M1Dc4d3TElrjwWW3oN1YtjnmKcUVbmNxSkNbUpJ2qIByDn2p00t1C0rqPTsjWVi1NKlabiOuXOapuHlch5Kxu8pvlaQMc8Hd7YrnHUB/p1b+n7lt1TqG8K07cnDFESHKVOQksoUpHKE7mwCoqWeSSeTVaOg3WBrp1GuiEX0WKD/EmXfK8ovOSmPUFBBwfLH6Sr7E4GRQXojay1HqBWktRzLGhFrul1Uy1FRKC3vKcDvlqKeAPQjKkknGeOxFQvrl06surNH23WLER3T18YuEdiI5awRLOHAnb5SfSlXqOeDtACvtSi4a91ZqDSenWLNLj2u5XCUfphNgfTPhCTubdSgggJUhWckjjJ98Vz7pR1J1zprXV3PWZcFMexOy3ZEYW9SHW9vKH21Jyl0qUoISvvg4zxQOnVjQWm7npCFo7qQh7UPUa7uKYtF3VKdDTe5SQXEnJDbbfoC0bcknPAORRHqFo1eguot30gu7MXRy2vGO7IjtLaTvH6k7VgEEHj4+K+hnUHWGk9W+HvV/UO4Lk6fEq1MqgPw1hchgqWUlafLIJBcSEq7EgYPAr5sTZVwuM16fcJT0uU+ouOvvLK1uKPdSiTkmgRpSraeT3rKUr8sj7f6V7AWEYrKQ55fGTn/wDlBqCVY9Pf715QlRScE/etqd+CMcVhsLLZPbFB/9k="

API_BASE = "https://discord.com/api/v10"
CDN_BASE = "https://cdn.discordapp.com"
PERM_ADMINISTRATOR = 0x8

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET", uuid.uuid4().hex)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
)

CATEGORY_NAMES = {"pve": "Host", "security": "Security", "support": "Support"}
ALL_CATEGORIES = list(CATEGORY_NAMES.keys())

PUBLIC_SITE_TABS = {"announcements", "leaderboards", "live", "schedule", "pulse", "members", "profile"}

FALLBACK_EVENT_POINTS = {
    "pve": {
        "Enmity": 1.5, "Elder": 2, "Titus": 3, "Hellmode": 15,
        "Deep Champion": 15, "Diluvian W (25)": 3, "Diluvian W (50)": 10,
        "Parasol": 5, "Layer 2 (1)": 3, "Layer 2 (2)": 7, "Other Bosses": 1,
    },
    "security": {
        "Security Vouch": 1, "Depths Vouch": 1.5,
        "Defense Vouch": 1, "Depths Defense Vouch": 1.5,
    },
    "support": {
        "Support Vouch": 1, "Backup Vouch": 2, "Depths Safe Vouch": 5,
    },
}

CATEGORY_EVENTS = FALLBACK_EVENT_POINTS  # kept for older references

# Events offered as routes to the next rank on the profile page, in this order.
# Anything not listed (or since renamed) is topped up with the highest value events.
GOAL_ROUTE_EVENTS = {
    "pve": ["Hellmode", "Deep Champion", "Enmity", "Elder"],
    "security": [],
    "support": [],
}

PERSONAS = ["default", "hype", "chill", "sarcastic", "formal"]

# Built-in ?commands that custom commands may not shadow
RESERVED_COMMANDS = {
    "shutdown", "sleep", "awake", "wakeup", "profile", "cleanleaderboards",
    "testeventping", "postleaderboards", "refreshleaderboards", "addmemory",
    "remember", "memories", "removememory", "forget", "persona", "personas",
    "leaderboard", "sleaderboard", "suleaderboard", "vouches", "addvouch",
    "backfill", "backfillhistory", "revertbackfill", "undobackfill",
    "syncvouches", "scanhistory", "commands", "help",
}

# Real in-game Deepwoken Attunement icons, sourced from the Deepwoken Wiki
# (https://deepwoken.fandom.com/wiki/Attunements), served locally via /badge-icon/<key>.png.
BADGE_ICON_B64 = {
    "thundercall": "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",
    "flamecharm": "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",
    "frostdraw": "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",
    "galebreathe": "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",
    "shadowcast": "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",
    "ironsing": "iVBORw0KGgoAAAANSUhEUgAAAKQAAACkCAYAAAAZtYVBAAAG3ElEQVR4nO3dTY5VRRjG8fdKD9WECQkMHCAkhjW4AKfugYEJLMBgCE2IxAVA4oA9OHUBroGYgAwcQMKERJ0SHJhquIXV9V311Dn/36Tp7nO7617e+3R9nXMOV6/feGfnePHs6cHMLHYccJ7UOvpkTHOANAdXsY8fPTEzs9cvX5mZ2f2Hd48OvHfngZmZXbpyeWT7sLjUerp1+6aZkZAQc+L+4VeyS0zHVTBQIlRPLikdEhJSDv6ox1Wyn4jfff/juFZhc37+6Yejz0N1RkJCyklsfsgl419//zOwWdgaV0d+UjquDklISDnrQ7rRjhtlk4zo4fPPPjWz90np1x0JCSln85D+CgzJiB78uvLrjoSEFAoSUihISKEgIYWChBQKElIoSEihICGFgoQUChJSKEhIoSAhhYKElJP4IVBw4c3z//3624vXBrekLxISUkhIMaEkdE5PT48++sevnpgkJKSQkCL8pHMJWPr5qkhISCEhxdQmo0vaVfuSJCSk7DYhY6PZ2QnjJ5/fnlCfc/W+JAkJKZtPyNR5vdDnamLPZ3UkJKQsm5C5SaGefL7YisxqzycVCQkpyyRkKBFbJYVK4vjJGGuXSrtbISEhRTYheydi6OfNmn90v9c979DoP/T8Z8+btkJCQkqzhOw1Pzaqj6iSMKEVGZUk742EhJTqhExdUx09GtxKX2u19tYiISGlWR8ylEiz58n2ljCrIyEhpfk85OxE9K2+g3pvSEhIKU7I3H2Go4V2y5CU2khISKnuQ6qfy7H1Kz1sDQkJKdkJqd53DAmtHNG31EJCQkpxH1K97xjDKFwTCQkpsjvGndJzS1KTm6TUQkJCSvfdPq1+buo5JqX7MVdPSvVrFaUiISGlepQ9Sux85dTPt5KUqWdlrrZCRUJCSnZCpp4VFzK6rxn7furxKkmZe42f2ec25SIhIaV6lJ2aGH6S1r5TSx+f+zjV3UK55zCpJ6NDQkLKsJWa1GvX+FTe2bN3C9XuslJ5HWNISEgZvpYdG6Wnzje26ouGfm7u8aOSsnSWoPXr1QsJCSnTd/vE+pa+1okY+7rqyo7fLv91DB2njoSElOkJ6aT2LXv/3tDvd3JXgmqV7uJZpc/oIyEhRSYhfaG+5agVntzE7p1Eod+bu+tHHQkJKbIJ6aQmZe5KT+4oOHU2YNTadmp7QqNxVSQkpMgnpJObULn7NHPbMVvuXS9U2h1DQkLKMgnppL7TV0mEkNQEVN8llYuEhJTm96mJWT25RitNullr7LVISEjpduWK0D68Vd6ps+TeBTe2grXa609CQkq3uzD4Vt19MkrqPsbQGnvocav9pSIhIaX7XRhIxvOlJlypWGKqJSUJCSnNEzL2jsR/SpMxlmj+6x3bLaWWlCQkpBQnZOpZbqvtx+utNBlDiRZ7XGxeUy0pSUhIGX6N8dnvwFlqk7H2uFX6lCQkpHS/PmTonbj1pKw9G7D1/GPq8bP/n0hISGnWh0y9fuHW5yVrV15a9xlT2xf7OCopSUhIaX5Ozd5WbFLn+WJix+degbi0DxlrV++kJCEhZdpZh6GVntBxKnJXPkJix4eed+59glr9RRqVlCQkpHTrQ9Y+bvZ8Za9Zg1gfMVfu9S1T2xM7vtf/DwkJKc0SstU9EGPzYKPFZg1ijwv9nN6zDbkraCGpo+9WSEhI6T7Kjr2DWt2FofW8X+5oOfXrKkoTNPS8Wt0DkoSElG4JWXqF2pDUHdKtVihyj69NRLXdT6XznbWvAwkJKctdH7J2tJv780u/HxtVjx5116qd70xFQkLKMglZeqevWKLmJm5te7aGtWxs2jIJ6cu9T0tu37D2Pjal7dg7EhJSlk1Ip/Xor1WfqDQR1eYjRyMhIWX5hAzpdTfZ2t+b+nGvSEhI2WxCpuqVSLMSenUkJKTsJiFT92W2FruOJsl5jISElM0nZO4VH3pL3QW0VyQkpOyuIE9PT6ek0NuL1476qbPaoW53BQltuylIP6FU2hFKygtvnk87F32m3RQk1rD5UXbI7P5b6pr33pCQkLK7hFToR34o98odW0dCQsruElKVWnLPQkJCCgUJKRQkpFCQkEJBQgoFCSkUJKRQkJBCQUIKBQkpFCSknK1lv3756ugbf/7xu5mZffHlV2NbhE1zdeX4dUdCQsrB/ePq9RvvzMweP3piZma3bt80M7Ovv/nWzEhK1HHJ+Nuvv5jZx3X24tnTgxkJCTEnLhlDXEW7pARKuDoKcXVIQkLK2Sj73p0HZvb+b7r7G++4rwMlQvXk6u7+w7tmRkJCzFlCXrpy2cw+TkrHfd0dB6Rw84yp9URCQsohNsp280Ox44DzpNYRCQkp/wJL/USNPJzctwAAAABJRU5ErkJggg==",
}

HOST_BADGE_TIERS = [
    {"threshold": 1, "name": "Thundercall", "icon": "thundercall"},
    {"threshold": 5, "name": "Flamecharm", "icon": "flamecharm"},
    {"threshold": 15, "name": "Frostdraw", "icon": "frostdraw"},
    {"threshold": 40, "name": "Galebreathe", "icon": "galebreathe"},
    {"threshold": 100, "name": "Shadowcast", "icon": "shadowcast"},
    {"threshold": 250, "name": "Ironsing", "icon": "ironsing"},
]


def host_badges(record):
    total = record.get("host_runs_total", 0)
    earned = [t for t in HOST_BADGE_TIERS if total >= t["threshold"]]
    next_tier = next((t for t in HOST_BADGE_TIERS if total < t["threshold"]), None)
    return {
        "total_hosted": total,
        "top": earned[-1] if earned else None,
        "earned": earned,
        "next": ({**next_tier, "remaining": next_tier["threshold"] - total} if next_tier else None),
    }


def top_host_badge(record):
    total = record.get("host_runs_total", 0)
    earned = [t for t in HOST_BADGE_TIERS if total >= t["threshold"]]
    return earned[-1] if earned else None


DEFAULT_CONFIG = {
    "pve_channel_id": 1529113596657799178,
    "security_channel_id": 1527834552150659103,
    "support_channel_id": 1527834504658550924,
    "live_leaderboard_channel_id": 1530286316628217906,
    "audit_log_channel_id": 1530317395669815438,
    "event_ping_channel_id": 1529142467658649640,
    "chime_in_channel_id": 1478405937080307806,
    "updates_channel_id": 1532474881915097118,
    "on_leave_button_channel_id": None,
    "on_leave_log_channel_id": None,
}

DEFAULT_EVENT_SCHEDULE = {
    "Carnival of Hearts": ["07:00","08:30","10:00","11:30","13:00","14:30","16:00","17:30","19:00","20:30","22:00","23:30","01:00","02:30","04:00","05:30"],
    "Interluminary Parasol": ["07:30","09:00","10:30","12:00","13:30","15:00","16:30","18:00","19:30","21:00","22:30","00:00","01:30","03:00","04:30","06:00"],
    "Battle Royale": ["08:00","09:30","11:00","12:30","14:00","15:30","17:00","18:30","20:00","21:30","23:00","00:30","02:00","03:30","05:00","06:30"],
    "Doom of Caeranthil": ["07:00","09:00","11:00","13:00","15:00","17:00","19:00","21:00","23:00","01:00","03:00","05:00"],
}

# Libya (Africa/Tripoli) is a fixed UTC+2 offset with no DST, so a plain
# fixed-offset timezone is enough - no zoneinfo dependency needed.
EVENT_SCHEDULE_TZ = timezone(timedelta(hours=2))

# ─────────────────────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────────────────────

def user_records(data):
    for uid, rec in data.items():
        if uid.isdigit():
            yield uid, rec

def combined_total(user_data):
    return sum(user_data.get(cat, {}).get("total_points", 0) for cat in ALL_CATEGORIES)

def ensure_user_cat(data, uid, category):
    uid = str(uid)
    data.setdefault(uid, {})
    if category not in data[uid]:
        data[uid][category] = {"total_points": 0, "total_vouches": 0, "events": {}, "cooldowns": {}, "log": []}
    # Seed from the live economy config (defaults + any admin overrides), not the
    # hardcoded fallback list, so a custom event added via the Economy tab doesn't
    # KeyError the first time someone's vouched for it.
    for e in get_economy(data)["events"].get(category, {}):
        data[uid][category]["events"].setdefault(e, 0)
    return data[uid][category]

# ─────────────────────────────────────────────────────────────
# SITE ACTIVITY
# Page loads are counted in memory and flushed to disk periodically, so a busy
# day does not mean rewriting the whole JSON file on every request.
# ─────────────────────────────────────────────────────────────

ANALYTICS_RETENTION_DAYS = 120
_visit_buffer = {}
_visit_lock = threading.Lock()
_last_flush = [0.0]


def record_visit(uid, page):
    """Count one page view. Cheap: memory only, flushed on a timer."""
    day = datetime.now(timezone.utc).date().isoformat()
    with _visit_lock:
        bucket = _visit_buffer.setdefault(day, {})
        entry = bucket.setdefault(str(uid), {"views": 0, "pages": {}})
        entry["views"] += 1
        entry["pages"][page] = entry["pages"].get(page, 0) + 1
        due = (time.time() - _last_flush[0]) > 45 or sum(
            len(v) for v in _visit_buffer.values()
        ) > 40
    if due:
        flush_visits()


def flush_visits():
    """Fold the in-memory counts into the data file."""
    with _visit_lock:
        if not _visit_buffer:
            _last_flush[0] = time.time()
            return
        pending = {day: {u: dict(v) for u, v in users.items()} for day, users in _visit_buffer.items()}
        _visit_buffer.clear()
        _last_flush[0] = time.time()

    with data_txn() as data:
        analytics = data.setdefault("_analytics", {})
        days = analytics.setdefault("days", {})
        last_seen = analytics.setdefault("last_seen", {})
        now_iso = datetime.now(timezone.utc).isoformat()

        for day, users in pending.items():
            stored_day = days.setdefault(day, {})
            for uid, entry in users.items():
                slot = stored_day.setdefault(uid, {"views": 0, "pages": {}})
                slot["views"] += entry["views"]
                for page, count in entry["pages"].items():
                    slot["pages"][page] = slot["pages"].get(page, 0) + count
                last_seen[uid] = now_iso

        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=ANALYTICS_RETENTION_DAYS)).isoformat()
        for day in [d for d in days if d < cutoff]:
            del days[day]


# ─────────────────────────────────────────────────────────────
# BOT BRIDGE
# The dashboard runs in a thread inside the bot process, so it can borrow the
# bot's member cache and schedule coroutines on its event loop.
# ─────────────────────────────────────────────────────────────

_bridge = {
    "bot": None, "loop": None, "guild_id": None,
    "thresholds": {}, "metric": {}, "resync": None, "events": {},
}
_name_cache = {}

def set_bot(bot, loop=None, thresholds=None, metric=None, resync=None, guild_id=None, events=None):
    """Called once from the bot's on_ready so the dashboard can resolve names etc."""
    _bridge["bot"] = bot
    _bridge["loop"] = loop
    _bridge["thresholds"] = thresholds or {}
    _bridge["metric"] = metric or {}
    _bridge["resync"] = resync
    _bridge["guild_id"] = guild_id
    _bridge["events"] = events or {}
    _name_cache.clear()


# ─────────────────────────────────────────────────────────────
# ECONOMY (event points and rank ladders, editable from the dashboard)
# Stored overrides win; the bot's constants are the fallback.
# ─────────────────────────────────────────────────────────────

def default_event_points():
    """The bot's CATEGORY_EVENTS flattened to {category: {event: points}}."""
    if _bridge["events"]:
        return {
            cat: {name: cfg.get("points", 0) for name, cfg in events.items()}
            for cat, events in _bridge["events"].items()
        }
    return {cat: dict(events) for cat, events in FALLBACK_EVENT_POINTS.items()}


def default_event_cooldowns():
    """The bot's CATEGORY_EVENTS flattened to {category: {event: cooldown_seconds}}."""
    if _bridge["events"]:
        return {
            cat: {name: cfg.get("cooldown", 0) for name, cfg in events.items()}
            for cat, events in _bridge["events"].items()
        }
    return {cat: {name: 0 for name in events} for cat, events in FALLBACK_EVENT_POINTS.items()}


def default_ranks():
    return {cat: [list(row) for row in ladder] for cat, ladder in (_bridge["thresholds"] or {}).items()}


def get_economy(data=None):
    """Merged view of event points, cooldowns, and rank ladders."""
    data = load_data() if data is None else data
    stored = data.get("_economy", {})
    events = default_event_points()
    events.update({c: dict(v) for c, v in (stored.get("events") or {}).items()})
    cooldowns = default_event_cooldowns()
    cooldowns.update({c: dict(v) for c, v in (stored.get("cooldowns") or {}).items()})
    ranks = default_ranks()
    ranks.update({c: [list(r) for r in v] for c, v in (stored.get("ranks") or {}).items()})
    return {"events": events, "cooldowns": cooldowns, "ranks": ranks}


def event_points(category, event, data=None):
    return get_economy(data)["events"].get(category, {}).get(event, 0)

def resolve_user(uid):
    """Discord display name + avatar for a user ID, falling back to the raw ID."""
    uid = str(uid)
    if uid in _name_cache:
        return _name_cache[uid]
    info = {"name": uid, "avatar": "", "resolved": False}
    bot = _bridge["bot"]
    if bot is not None:
        try:
            member = None
            for guild in getattr(bot, "guilds", []):
                member = guild.get_member(int(uid))
                if member:
                    break
            user = member or bot.get_user(int(uid))
            if user is not None:
                info = {
                    "name": getattr(user, "display_name", None) or user.name,
                    "avatar": str(user.display_avatar.url) if getattr(user, "display_avatar", None) else "",
                    "resolved": True,
                }
                _name_cache[uid] = info
        except (ValueError, AttributeError):
            pass
    return info

def rank_progress(category, points, vouches, data=None):
    """Current rank role, next rank and how far along the user is."""
    ladder = get_economy(data)["ranks"].get(category) or []
    if not ladder:
        return None
    value = vouches if _bridge["metric"].get(category) == "vouches" else points
    current = None
    current_at = 0
    nxt = None
    for threshold, name in ladder:
        if value >= threshold:
            current, current_at = name, threshold
        elif nxt is None:
            nxt = (threshold, name)
    if nxt is None:
        pct = 100
        remaining = 0
        next_name = None
        next_at = None
    else:
        next_at, next_name = nxt
        span = max(1, next_at - current_at)
        pct = max(0, min(100, round(((value - current_at) / span) * 100)))
        remaining = round(max(0, next_at - value), 1)
    return {
        "current": current, "next": next_name, "next_at": next_at,
        "pct": pct, "remaining": remaining, "value": round(value, 1),
    }

def run_on_bot(coro):
    """Schedule a coroutine on the bot's loop from this Flask thread."""
    loop = _bridge["loop"]
    if loop is None or coro is None:
        return None
    import asyncio
    return asyncio.run_coroutine_threadsafe(coro, loop)


async def _get_channel(channel_id):
    bot = _bridge["bot"]
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    return channel


UPDATE_PING_ROLE_NAME = "Bot Update"


def _build_update_embed(content, posted_by, posted_at):
    embed = discord.Embed(
        title="Bot Update",
        description=content,
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"Posted by {posted_by}")
    try:
        embed.timestamp = datetime.fromisoformat(posted_at)
    except (TypeError, ValueError):
        pass
    return embed


def _update_ping_kwargs(guild):
    """content/allowed_mentions kwargs to ping the Bot Update role, if it exists."""
    role = discord.utils.get(guild.roles, name=UPDATE_PING_ROLE_NAME) if guild else None
    if not role:
        return {}
    return {"content": role.mention, "allowed_mentions": discord.AllowedMentions(roles=True)}


async def _post_update_message(channel_id, content, posted_by, posted_at):
    channel = await _get_channel(channel_id)
    message = await channel.send(
        embed=_build_update_embed(content, posted_by, posted_at),
        **_update_ping_kwargs(getattr(channel, "guild", None)),
    )
    return str(message.id)


async def _edit_update_message(channel_id, message_id, content, posted_by, posted_at):
    channel = await _get_channel(channel_id)
    message = await channel.fetch_message(int(message_id))
    await message.edit(
        embed=_build_update_embed(content, posted_by, posted_at),
        **_update_ping_kwargs(getattr(channel, "guild", None)),
    )

# ─────────────────────────────────────────────────────────────
# DISCORD OAUTH2  (login with Discord, Administrator required)
# ─────────────────────────────────────────────────────────────

def oauth_configured():
    return bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI)

def avatar_url(user):
    if user.get("avatar"):
        ext = "gif" if str(user["avatar"]).startswith("a_") else "png"
        return f"{CDN_BASE}/avatars/{user['id']}/{user['avatar']}.{ext}?size=128"
    index = (int(user["id"]) >> 22) % 6
    return f"{CDN_BASE}/embed/avatars/{index}.png"

def guild_icon_url(guild):
    if guild.get("icon"):
        return f"{CDN_BASE}/icons/{guild['id']}/{guild['icon']}.png?size=128"
    return ""

def is_admin_guild(guild):
    """True if the logged-in user is the owner or holds Administrator in this guild."""
    if guild.get("owner"):
        return True
    try:
        return (int(guild.get("permissions", 0)) & PERM_ADMINISTRATOR) == PERM_ADMINISTRATOR
    except (ValueError, TypeError):
        return False

def discord_get(path, token):
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "MatzysOverseer (dashboard, 1.0)"},
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode())

def live_admin_guild_ids(user_id, guild_ids):
    """Re-checks Administrator/owner status against the bot's live guild cache -
    free and in-memory (no Discord API call), kept current in real time by the
    gateway - instead of trusting a session that could be weeks old. A session
    outlives a Discord permission change; this makes sure a demoted admin loses
    dashboard access the moment the bot's cache reflects it, not 31 days later
    when their cookie finally expires."""
    bot = _bridge.get("bot")
    if bot is None:
        return list(guild_ids)  # bot not connected yet - do not lock people out

    still_valid = []
    any_resolved = False
    for gid in guild_ids:
        guild = bot.get_guild(int(gid))
        if guild is None:
            continue
        any_resolved = True
        member = guild.get_member(int(user_id))
        if member is None:
            continue
        if member.id == guild.owner_id or member.guild_permissions.administrator:
            still_valid.append(gid)

    if not any_resolved:
        return list(guild_ids)  # bot hasn't cached any of these guilds (yet) - do not lock out
    return still_valid


def is_admin():
    if not (session.get("user") and session.get("role") == "admin" and session.get("admin_guilds")):
        return False
    guild_ids = [g["id"] for g in session["admin_guilds"]]
    return bool(live_admin_guild_ids(session["user"]["id"], guild_ids))


def admin_required(f):
    """Blocks anything that isn't a Discord-authenticated server administrator."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


WHITELIST_MANAGER_ROLE_ID = 1481379874366292008
WHITELIST_MANAGER_USER_ID = "1387930623766827140"


def is_whitelist_manager():
    """Only this specific role or this specific person can add/remove anti-nuke
    whitelist entries - being a dashboard admin isn't enough on its own."""
    if not is_admin():
        return False
    if session["user"]["id"] == WHITELIST_MANAGER_USER_ID:
        return True
    bot = _bridge.get("bot")
    if bot is None:
        return False
    for g in session.get("admin_guilds", []):
        guild = bot.get_guild(int(g["id"]))
        if guild is None:
            continue
        member = guild.get_member(int(session["user"]["id"]))
        if member and any(r.id == WHITELIST_MANAGER_ROLE_ID for r in member.roles):
            return True
    return False


def whitelist_manager_required(f):
    """Blocks anything that isn't the designated whitelist manager role/person,
    even for otherwise-valid dashboard admins."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_whitelist_manager():
            return jsonify({"error": "Only the designated whitelist managers can do that."}), 403
        return f(*args, **kwargs)
    return decorated


def member_required(f):
    """Any signed-in member of the server. Admins pass this too."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

@app.route("/api/admin/export-data")
@admin_required
def export_data():
    """Raw dump of the shared data store, for backing up/migrating off a host."""
    payload = json.dumps(load_data(), indent=2)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=vouches-backup.json"},
    )


@app.route("/api/admin/import-data", methods=["GET", "POST"])
@admin_required
def import_data():
    """Restore the data store from a backup file exported via /api/admin/export-data.
    Overwrites the entire live data store -- meant for seeding a fresh deployment."""
    if request.method == "GET":
        return """<!doctype html><html><head><title>Import data</title></head>
<body style="font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 20px;">
<h2>Import data backup</h2>
<p style="color:#b33;font-weight:bold;">This replaces the ENTIRE live data store with the
uploaded file. Cannot be undone.</p>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="file" accept="application/json" required><br><br>
  <label><input type="checkbox" name="confirm" required> I understand this overwrites all live data</label><br><br>
  <button type="submit">Import</button>
</form>
</body></html>"""

    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file uploaded"}), 400
    try:
        data = json.load(f.stream)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return jsonify({"error": "File is not valid JSON"}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object at the top level"}), 400
    save_data(data)
    return jsonify({"ok": True, "top_level_keys": list(data.keys())})


@app.route("/badge-icon/<key>.png")
def badge_icon(key):
    b64 = BADGE_ICON_B64.get(key)
    if not b64:
        return "", 404
    return Response(base64.b64decode(b64), mimetype="image/png",
                     headers={"Cache-Control": "public, max-age=604800"})


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr


@app.before_request
def log_ip_access():
    if session.get("user"):
        user_id = session.get("user", {}).get("id")
        ip = get_client_ip()
        if user_id and ip:
            from data_store import log_ip
            try:
                log_ip(user_id, ip)
            except Exception:
                pass


@app.route("/verify", methods=["GET", "POST"])
def verify():
    if not session.get("user"):
        return redirect("/login")

    user_id = session.get("user", {}).get("id")
    ip = get_client_ip()

    from data_store import is_ip_banned, is_fingerprint_banned, log_fingerprint, log_ip

    if request.method == "POST":
        fingerprint = request.json.get("fingerprint", "").strip()
        if not fingerprint:
            return jsonify({"error": "No fingerprint provided"}), 400

        if is_ip_banned(ip) or is_fingerprint_banned(fingerprint):
            return jsonify({"verified": False, "banned": True}), 403

        log_ip(user_id, ip)
        log_fingerprint(user_id, fingerprint)

        try:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                member = guild.get_member(int(user_id))
                if member:
                    event_access_role = discord.utils.get(guild.roles, name="event access")
                    no_access_role = discord.utils.get(guild.roles, name="no access")

                    if event_access_role:
                        asyncio.run_coroutine_threadsafe(
                            member.add_roles(event_access_role),
                            bot.loop
                        )
                    if no_access_role:
                        asyncio.run_coroutine_threadsafe(
                            member.remove_roles(no_access_role),
                            bot.loop
                        )
        except Exception as e:
            print(f"[Verify] Role assignment failed: {e}")

        return jsonify({"verified": True})

    if is_ip_banned(ip):
        return render_template_string("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Access Denied - Matzys Overseer</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0c1210;--header:#0d1614;--card:#0d1614;--card-2:#152220;
  --border:#233530;--border-2:#324b44;
  --moon:#7fc2b8;--moon-dim:#a8ddd2;--steel:#9c8fe0;--sage:#5fcf9f;--red:#c77a80;--amber:#d1a86a;
  --text:#eef4f2;--muted:#8fa39d;--dim:#5c6f69;
}
body{background:var(--bg);color:var(--text);font-family:'Space Grotesk',-apple-system,"Segoe UI",system-ui,sans-serif;
  min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:20px}
.verify-container{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:40px;max-width:400px;width:100%;text-align:center}
.verify-icon{font-size:64px;margin-bottom:20px}
h1{font-size:24px;margin-bottom:10px;color:var(--red)}
p{color:var(--muted);margin-bottom:20px;font-size:14px}
</style>
</head>
<body>
<div class="verify-container">
<div class="verify-icon">🚫</div>
<h1>Access Denied</h1>
<p>Your IP address has been banned from this server.</p>
</div>
</body>
</html>"""), 403

    return render_template_string("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verification - Matzys Overseer</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0c1210;--header:#0d1614;--card:#0d1614;--card-2:#152220;
  --border:#233530;--border-2:#324b44;
  --moon:#7fc2b8;--moon-dim:#a8ddd2;--steel:#9c8fe0;--sage:#5fcf9f;--red:#c77a80;--amber:#d1a86a;
  --text:#eef4f2;--muted:#8fa39d;--dim:#5c6f69;
}
body{background:var(--bg);color:var(--text);font-family:'Space Grotesk',-apple-system,"Segoe UI",system-ui,sans-serif;
  min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:20px}
.verify-container{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:40px;max-width:400px;width:100%;text-align:center}
.verify-icon{font-size:64px;margin-bottom:20px;animation:bounce .6s ease}
@keyframes bounce{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
h1{font-size:28px;margin-bottom:10px;color:var(--sage)}
p{color:var(--muted);margin:16px 0;font-size:14px}
.button{display:inline-block;background:var(--moon);color:var(--bg);padding:12px 24px;border-radius:6px;text-decoration:none;
  font-weight:600;border:none;cursor:pointer;font-family:inherit;font-size:14px;transition:background .2s;margin-top:16px}
.button:hover{background:var(--moon-dim)}
.loading{animation:pulse 1.5s infinite}@keyframes pulse{0%,100%{opacity:.6}50%{opacity:1}}
</style>
</head>
<body>
<div class="verify-container">
<div class="verify-icon loading">⏳</div>
<h1>Verifying...</h1>
<p>Collecting device information and verifying your access.</p>
</div>
<script>
async function generateFingerprint(){
  const fingerprints={};
  fingerprints.browser=navigator.userAgent;
  fingerprints.language=navigator.language;
  fingerprints.timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;
  fingerprints.screen=`${screen.width}x${screen.height}`;
  fingerprints.colorDepth=screen.colorDepth;
  fingerprints.cores=navigator.hardwareConcurrency;
  fingerprints.memory=navigator.deviceMemory;

  const canvas=document.createElement('canvas');
  const ctx=canvas.getContext('2d');
  ctx.textBaseline='top';
  ctx.font='14px Arial';
  ctx.fillText('🔐',10,10);
  fingerprints.canvas=canvas.toDataURL().substring(0,50);

  const gl=canvas.getContext('webgl')||canvas.getContext('experimental-webgl');
  if(gl){
    fingerprints.webgl=gl.getParameter(gl.RENDERER);
  }

  return JSON.stringify(fingerprints);
}

generateFingerprint().then(async fp=>{
  try{
    const res=await fetch('/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fingerprint:fp})});
    if(res.ok){
      document.querySelector('.verify-icon').textContent='✅';
      document.querySelector('h1').textContent='Verified!';
      document.querySelector('p').textContent='Your access has been verified successfully.';
      document.querySelector('.verify-container').innerHTML+='<p>You\'ve been granted access to server events and assigned the event access role.</p><a href="/" class="button">Return to Dashboard</a>';
    }else{
      document.querySelector('.verify-icon').textContent='🚫';
      document.querySelector('h1').textContent='Access Denied';
      document.querySelector('p').textContent='Your device has been banned from accessing this server.';
    }
  }catch(e){
    document.querySelector('.verify-icon').textContent='❌';
    document.querySelector('h1').textContent='Error';
    document.querySelector('p').textContent='An error occurred during verification.';
  }
});
</script>
</body>
</html>""")


@app.route("/dashboard/admin/ips")
def admin_ips():
    if not session.get("user"):
        return redirect("/login")
    user_id = session.get("user", {}).get("id")
    if int(user_id) != 1387930623766827140:
        return jsonify({"error": "Access denied"}), 403

    from data_store import load_data

    data = load_data()
    ip_logs = data.get("_ip_logs", {})
    ip_bans = data.get("_ip_bans", {})

    ips_info = []
    for ip, users in ip_logs.items():
        banned = ip in ip_bans
        ips_info.append({
            "ip": ip,
            "users": list(users.keys()),
            "banned": banned,
            "last_seen": max(users.values()) if users else None
        })

    ips_info.sort(key=lambda x: x["last_seen"] or "", reverse=True)

    html = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>IP Management - Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0c1210;color:#eef4f2;font-family:system-ui;padding:20px}
.container{max-width:1200px;margin:0 auto}
h1{margin-bottom:20px;color:#7fc2b8}
.search-box{margin-bottom:20px;display:flex;gap:10px}
.search-box input{flex:1;padding:10px;background:#152220;border:1px solid #233530;color:#eef4f2;border-radius:4px}
.search-box button{padding:10px 20px;background:#7fc2b8;color:#0c1210;border:none;border-radius:4px;cursor:pointer;font-weight:600}
.search-box button:hover{background:#a8ddd2}
.user-details{background:#0d1614;border:1px solid #233530;border-radius:4px;padding:20px;margin-bottom:20px;display:none}
.user-details.show{display:block}
.user-details h2{color:#7fc2b8;margin-bottom:10px}
.user-info{background:#152220;padding:15px;border-radius:4px;margin-bottom:15px}
.user-info p{margin:8px 0;color:#8fa39d;word-break:break-all}
.user-info code{background:#0c1210;padding:2px 6px;border-radius:3px;color:#7fc2b8}
table{width:100%;border-collapse:collapse;background:#0d1614;border:1px solid #233530}
th,td{padding:12px;text-align:left;border-bottom:1px solid #233530}
th{background:#152220;font-weight:600}
.banned{background:rgba(199,122,128,.1);color:#c77a80}
.copy-btn{background:#152220;border:1px solid #233530;color:#7fc2b8;padding:4px 8px;cursor:pointer;border-radius:4px;font-size:12px}
.copy-btn:hover{background:#233530}
a{color:#7fc2b8;text-decoration:none;cursor:pointer}
a:hover{text-decoration:underline}
</style>
</head><body>
<div class="container">
<h1>IP Management</h1>
<div class="search-box">
<input type="text" id="userSearch" placeholder="Search by User ID...">
<button onclick="searchUser()">Search</button>
</div>
<div class="user-details" id="userDetails"></div>
<p style="margin-bottom:20px;color:#8fa39d">Total IPs: """ + str(len(ips_info)) + """ | Banned: """ + str(sum(1 for x in ips_info if x["banned"])) + """</p>
<table>
<thead><tr><th>IP Address</th><th>Users</th><th>Status</th><th>Last Seen</th></tr></thead>
<tbody>
"""

    for info in ips_info:
        status = '<span class="banned">🚫 BANNED</span>' if info["banned"] else '✅ Active'
        users_html = ", ".join([f'<a onclick="searchUserById(\'{u}\')">{u}</a>' for u in info["users"]])
        html += f"""<tr class="{'banned' if info['banned'] else ''}">
<td><code>{info['ip']}</code> <button class="copy-btn" onclick="navigator.clipboard.writeText('{info['ip']}')">Copy</button></td>
<td>{users_html}</td>
<td>{status}</td>
<td>{info['last_seen'][:10] if info['last_seen'] else 'N/A'}</td>
</tr>"""

    html += """</tbody></table>
</div>
<script>
function searchUserById(uid){
  document.getElementById('userSearch').value=uid;
  searchUser();
}
function searchUser(){
  const uid=document.getElementById('userSearch').value.trim();
  if(!uid)return;
  fetch(`/api/user_details?user_id=${uid}`).then(r=>r.json()).then(data=>{
    const el=document.getElementById('userDetails');
    if(data.error){
      el.textContent='User not found';
      el.classList.add('show');
    }else{
      el.innerHTML=`<h2>User Details: ${data.user_id}</h2>
<div class="user-info">
<p><strong>IPs (${data.ips.length}):</strong></p>
${data.ips.map(ip=>`<div style="margin-left:10px"><code>${ip.ip}</code> <span style="color:#8fa39d">${ip.last_seen}</span> ${ip.banned?'<span style="color:#c77a80">🚫 BANNED</span>':''}</div>`).join('')}
</div>
<div class="user-info">
<p><strong>Fingerprints (${data.fingerprints.length}):</strong></p>
${data.fingerprints.map(fp=>{try{const obj=JSON.parse(fp.fingerprint);return `<div style="margin-left:10px;margin-bottom:10px;background:#0c1210;padding:10px;border-radius:4px;font-size:12px"><div style="color:#7fc2b8;margin-bottom:5px"><strong>Browser:</strong> <code>${obj.browser?.substring(0,60)}</code></div><div><strong>Screen:</strong> ${obj.screen} | <strong>Color Depth:</strong> ${obj.colorDepth}</div><div><strong>Cores:</strong> ${obj.cores} | <strong>Memory:</strong> ${obj.memory}GB | <strong>Lang:</strong> ${obj.language}</div><div><strong>TZ:</strong> ${obj.timezone}</div><div style="margin-top:5px"><strong>Canvas:</strong> <code>${obj.canvas?.substring(0,40)}</code></div><div><strong>WebGL:</strong> <code>${obj.webgl?.substring(0,50)}</code></div>${fp.banned?'<div style="color:#c77a80;margin-top:8px">🚫 BANNED</div>':''}</div>`;}catch(e){return `<div style="margin-left:10px"><code>${fp.fingerprint}</code></div>`;}}).join('')}
</div>`;
      el.classList.add('show');
    }
  }).catch(e=>{
    document.getElementById('userDetails').textContent='Error loading user details';
    document.getElementById('userDetails').classList.add('show');
  });
}
</script>
</body></html>"""

    return html


@app.route("/api/user_details")
def api_user_details():
    if not session.get("user"):
        return jsonify({"error": "Not authenticated"}), 401
    user_id = session.get("user", {}).get("id")
    if int(user_id) != 1387930623766827140:
        return jsonify({"error": "Access denied"}), 403

    query_user_id = request.args.get("user_id", "").strip()
    if not query_user_id:
        return jsonify({"error": "No user_id provided"}), 400

    from data_store import load_data

    data = load_data()
    ip_logs = data.get("_ip_logs", {})
    ip_bans = data.get("_ip_bans", {})
    fingerprint_logs = data.get("_fingerprint_logs", {})
    fingerprint_bans = data.get("_fingerprint_bans", {})

    ips = []
    for ip, users in ip_logs.items():
        if query_user_id in users:
            ips.append({
                "ip": ip,
                "last_seen": users.get(query_user_id, "N/A"),
                "banned": ip in ip_bans
            })

    fingerprints = []
    for fp, users in fingerprint_logs.items():
        if query_user_id in users:
            fingerprints.append({
                "fingerprint": fp,
                "last_seen": users.get(query_user_id, "N/A"),
                "banned": fp in fingerprint_bans
            })

    if not ips and not fingerprints:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "user_id": query_user_id,
        "ips": sorted(ips, key=lambda x: x["last_seen"], reverse=True),
        "fingerprints": sorted(fingerprints, key=lambda x: x["last_seen"], reverse=True)
    })


@app.route("/login")
def login():
    if session.get("user") and session.get("admin_guilds"):
        return redirect("/")
    return render_template_string(
        LOGIN_HTML,
        configured=oauth_configured(),
        error=request.args.get("error", ""),
    )

@app.route("/login/discord")
def login_discord():
    if not oauth_configured():
        return redirect("/login?error=" + urllib.parse.quote(
            "Discord login isn't set up yet. Add DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI."
        ))
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",
    })
    return redirect(f"https://discord.com/oauth2/authorize?{params}")

@app.route("/callback")
def oauth_callback():
    def fail(msg):
        return redirect("/login?error=" + urllib.parse.quote(msg))

    if request.args.get("error"):
        return fail("Discord login was cancelled.")

    state = request.args.get("state", "")
    if not state or state != session.pop("oauth_state", None):
        return fail("Login expired or was tampered with. Try again.")

    code = request.args.get("code", "")
    if not code:
        return fail("Discord didn't return a login code. Try again.")

    payload = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }).encode()
    token_req = urllib.request.Request(
        f"{API_BASE}/oauth2/token",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "MatzysOverseer (dashboard, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(token_req, timeout=15) as res:
            access_token = json.loads(res.read().decode())["access_token"]
        user = discord_get("/users/@me", access_token)
        guilds = discord_get("/users/@me/guilds", access_token)
    except urllib.error.HTTPError as e:
        print(f"[Dashboard] Discord OAuth error {e.code}: {e.read()[:300]}")
        return fail("Discord rejected the login. Check your client ID, secret and redirect URI.")
    except (urllib.error.URLError, TimeoutError):
        return fail("Couldn't reach Discord. Try again in a moment.")
    except (KeyError, ValueError):
        return fail("Discord returned an unexpected response. Try again.")

    # Members just need to share a server with the bot.
    bot_guild_ids = {str(g.id) for g in getattr(_bridge["bot"], "guilds", [])}
    if REQUIRED_GUILD_ID:
        in_server = any(str(g["id"]) == REQUIRED_GUILD_ID for g in guilds)
    elif bot_guild_ids:
        in_server = any(str(g["id"]) in bot_guild_ids for g in guilds)
    else:
        in_server = True  # bot not ready yet, do not lock people out

    admin_guilds = [g for g in guilds if is_admin_guild(g)]
    if REQUIRED_GUILD_ID:
        admin_guilds = [g for g in admin_guilds if str(g["id"]) == REQUIRED_GUILD_ID]
    elif bot_guild_ids:
        # "Empty GUILD_ID = any server you admin" only ever meant any server the
        # BOT is also in - without this, admin-ing any unrelated Discord server
        # (e.g. a throwaway personal one) was enough to get admin here.
        admin_guilds = [g for g in admin_guilds if str(g["id"]) in bot_guild_ids]
    if ALLOWED_USER_IDS and str(user["id"]) not in ALLOWED_USER_IDS:
        admin_guilds = []  # allowlist gates admin access only, not member access

    if not admin_guilds and not in_server:
        return fail("You are not in the bot's server, so there is nothing here for you yet.")

    session["role"] = "admin" if admin_guilds else "member"
    session["user"] = {
        "id": str(user["id"]),
        "username": user.get("global_name") or user.get("username", "Admin"),
        "handle": user.get("username", ""),
        "avatar": avatar_url(user),
    }
    session["admin_guilds"] = [
        {"id": str(g["id"]), "name": g["name"], "icon": guild_icon_url(g)}
        for g in sorted(admin_guilds, key=lambda g: g["name"].lower())
    ]
    session.permanent = True
    return redirect("/fingerprint-check" if session["role"] == "admin" else "/profile")

@app.route("/fingerprint-check")
def fingerprint_check():
    if not session.get("user"):
        return redirect("/login")

    return render_template_string("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Loading - Matzys Overseer</title>
<style>
body{background:#0c1210;color:#eef4f2;font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.loader{text-align:center}
.spinner{width:40px;height:40px;border:4px solid #233530;border-top:4px solid #7fc2b8;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="loader">
<div class="spinner"></div>
<p>Loading...</p>
</div>
<script>
async function generateFingerprint(){
  const fingerprints={};
  fingerprints.browser=navigator.userAgent;
  fingerprints.language=navigator.language;
  fingerprints.timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;
  fingerprints.screen=`${screen.width}x${screen.height}`;
  fingerprints.colorDepth=screen.colorDepth;
  fingerprints.cores=navigator.hardwareConcurrency;
  fingerprints.memory=navigator.deviceMemory;

  const canvas=document.createElement('canvas');
  const ctx=canvas.getContext('2d');
  ctx.textBaseline='top';
  ctx.font='14px Arial';
  ctx.fillText('🔐',10,10);
  fingerprints.canvas=canvas.toDataURL().substring(0,50);

  const gl=canvas.getContext('webgl')||canvas.getContext('experimental-webgl');
  if(gl){
    fingerprints.webgl=gl.getParameter(gl.RENDERER);
  }

  return JSON.stringify(fingerprints);
}

generateFingerprint().then(async fp=>{
  try{
    const res=await fetch('/api/check-dashboard-fingerprint',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fingerprint:fp})});
    const data=await res.json();
    if(data.ok){
      window.location.href='/';
    }else{
      document.body.innerHTML='<div style="text-align:center;padding:40px"><h1>Access Denied</h1><p>Your device has been banned.</p></div>';
    }
  }catch(e){
    document.body.innerHTML='<div style="text-align:center;padding:40px"><h1>Error</h1><p>An error occurred. Please try logging in again.</p></div>';
  }
});
</script>
</body>
</html>""")


@app.route("/api/check-dashboard-fingerprint", methods=["POST"])
def check_dashboard_fingerprint():
    if not session.get("user"):
        return jsonify({"error": "Not authenticated"}), 401

    fingerprint = request.json.get("fingerprint", "").strip()
    if not fingerprint:
        return jsonify({"error": "No fingerprint provided"}), 400

    from data_store import is_fingerprint_banned, log_fingerprint

    user_id = session.get("user", {}).get("id")
    if is_fingerprint_banned(fingerprint):
        return jsonify({"ok": False, "banned": True}), 403

    log_fingerprint(user_id, fingerprint)
    return jsonify({"ok": True})


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/terms")
def terms():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Terms of Service - Pve-Bot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0c1210;color:#eef4f2;font-family:'Space Grotesk',-apple-system,sans-serif;line-height:1.6;padding:40px 20px}
.container{max-width:960px;margin:0 auto;background:#0d1614;border:1px solid #233530;border-radius:4px;padding:40px}
h1{font-size:28px;margin-bottom:20px;color:#7fc2b8}
h2{font-size:20px;margin-top:30px;margin-bottom:15px;color:#7fc2b8}
p{margin-bottom:12px;color:#eef4f2}
li{margin-left:20px;margin-bottom:8px}
a{color:#7fc2b8;text-decoration:none}
a:hover{text-decoration:underline}
.back{display:inline-block;margin-bottom:20px;padding:8px 16px;background:#152220;border-radius:4px;border:1px solid #233530}
</style>
</head>
<body>
<div class="container">
<a href="/" class="back">← Back to dashboard</a>
<h1>Terms of Service - Pve-Bot</h1>
<p><strong>Last Updated:</strong> September 11, 2026</p>

<h2>1. Agreement to Terms</h2>
<p>By using Pve-Bot (the "Service"), you agree to these Terms of Service. If you don't agree, don't use the bot. We may update these terms at any time, and continued use means you accept changes.</p>

<h2>2. Description of Service</h2>
<p>Pve-Bot is a Discord bot that provides:</p>
<ul>
<li>Vouch tracking and management system</li>
<li>Leaderboards and statistics</li>
<li>User threat scoring and behavioral analysis</li>
<li>On-leave/role management</li>
<li>Admin audit logging</li>
</ul>

<h2>3. User Responsibilities</h2>
<p>You agree to:</p>
<ul>
<li><strong>Use the bot legally</strong> - Don't use it for illegal activities, harassment, or abuse</li>
<li><strong>Respect Discord ToS</strong> - This bot is subject to Discord's Terms of Service</li>
<li><strong>Don't circumvent systems</strong> - No hacking, exploiting, or bypassing security features</li>
<li><strong>Accurate information</strong> - Vouches must be honest and accurate</li>
<li><strong>No spam</strong> - Don't abuse commands or flood the server</li>
</ul>
<p>Violations may result in bot removal from your server.</p>

<h2>4. Prohibited Activities</h2>
<p>Don't use Pve-Bot to:</p>
<ul>
<li>Harass, threaten, or abuse other users</li>
<li>Spam commands or flood the server</li>
<li>Manipulate vouch counts or leaderboards</li>
<li>Reverse-engineer or modify the bot code without permission</li>
<li>Attempt to gain unauthorized access to data</li>
<li>Violate Discord's Terms of Service or Community Guidelines</li>
</ul>

<h2>5. Admin Authority</h2>
<p>Server administrators have authority to:</p>
<ul>
<li>Manage vouch data (add, remove, revert)</li>
<li>Configure bot settings for their server</li>
<li>Remove users from tracking systems</li>
<li>Access audit logs</li>
</ul>
<p>The bot tracks administrative actions and logs them for security purposes.</p>

<h2>6. Data Retention</h2>
<p>Your data is stored while:</p>
<ul>
<li>You are a member of a server using Pve-Bot</li>
<li>Administrators haven't deleted your records</li>
<li>The server hasn't removed the bot</li>
</ul>
<p>You can request data deletion from server admins or the bot owners.</p>

<h2>7. Limitation of Liability</h2>
<p><strong>THE BOT IS PROVIDED "AS-IS" WITHOUT WARRANTIES. WE ARE NOT LIABLE FOR:</strong></p>
<ul>
<li>Data loss or corruption</li>
<li>Service interruptions or downtime</li>
<li>Leaderboard inaccuracies</li>
<li>Decisions made based on bot data</li>
</ul>
<p>Use this bot at your own risk. Don't rely on it as your sole source of important decisions.</p>

<h2>8. Disclaimers</h2>
<ul>
<li><strong>No Guarantees:</strong> The bot may have bugs or unexpected behavior</li>
<li><strong>Third-party Service:</strong> The bot uses Discord's services and is subject to their policies</li>
<li><strong>No Legal Advice:</strong> Threat scores and vouchings are not legal determinations</li>
<li><strong>Community Tool:</strong> The bot is meant for community management, not legal enforcement</li>
</ul>

<h2>9. Server Admin Liability</h2>
<p>Server administrators are responsible for:</p>
<ul>
<li>Compliance with Discord ToS</li>
<li>Proper use of bot features</li>
<li>User privacy in their community</li>
<li>Vouch data accuracy</li>
</ul>

<h2>10. Bot Removal</h2>
<p>We reserve the right to:</p>
<ul>
<li>Remove the bot from servers violating these terms</li>
<li>Disable features that enable abuse</li>
<li>Suspend or terminate access for bad actors</li>
</ul>

<h2>11. Changes to Terms</h2>
<p>We may update these terms anytime. Continued use = acceptance.</p>

<h2>12. Governing Law</h2>
<p>These terms are governed by applicable law. Disputes should be resolved through Discord's mechanisms first.</p>

<h2>13. Contact</h2>
<p>For terms questions: Contact the bot developers via <a href="https://github.com/Yuki-Onnaa/Pve-Bot">GitHub</a> or Discord support channels.</p>

<p><strong>By inviting Pve-Bot to your server, you accept these Terms of Service.</strong></p>
</div>
</body>
</html>"""
    return html

@app.route("/privacy")
def privacy():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Policy - Pve-Bot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0c1210;color:#eef4f2;font-family:'Space Grotesk',-apple-system,sans-serif;line-height:1.6;padding:40px 20px}
.container{max-width:960px;margin:0 auto;background:#0d1614;border:1px solid #233530;border-radius:4px;padding:40px}
h1{font-size:28px;margin-bottom:20px;color:#7fc2b8}
h2{font-size:20px;margin-top:30px;margin-bottom:15px;color:#7fc2b8}
p{margin-bottom:12px;color:#eef4f2}
li{margin-left:20px;margin-bottom:8px}
a{color:#7fc2b8;text-decoration:none}
a:hover{text-decoration:underline}
.back{display:inline-block;margin-bottom:20px;padding:8px 16px;background:#152220;border-radius:4px;border:1px solid #233530}
</style>
</head>
<body>
<div class="container">
<a href="/" class="back">← Back to dashboard</a>
<h1>Privacy Policy - Pve-Bot</h1>
<p><strong>Last Updated:</strong> September 11, 2026</p>

<h2>1. Overview</h2>
<p>Pve-Bot ("we", "us", "the Service") is committed to protecting your privacy. This policy explains what data we collect, how we use it, and your rights.</p>

<h2>2. What Data We Collect</h2>
<p>We collect and store:</p>

<h3 style="font-size:16px;margin-top:15px">User Identifiers</h3>
<ul>
<li><strong>Discord User ID</strong> (required to track vouches)</li>
<li><strong>Discord Username/Display Name</strong> (for display purposes)</li>
<li><strong>Server/Guild ID</strong> (to organize data by server)</li>
</ul>

<h3 style="font-size:16px;margin-top:15px">Vouch Data</h3>
<ul>
<li><strong>Vouch records</strong> - Category, event type, count, points</li>
<li><strong>Who vouched for you</strong> (user ID of voucher)</li>
<li><strong>When vouched</strong> (timestamp)</li>
<li><strong>Vouch comments/notes</strong> (if provided)</li>
</ul>

<h3 style="font-size:16px;margin-top:15px">Behavioral Data</h3>
<ul>
<li><strong>Threat scores</strong> (calculated from vouches and behavior)</li>
<li><strong>On-leave status</strong> (duration, reason)</li>
<li><strong>Role changes and removals</strong></li>
<li><strong>Leaderboard positions</strong></li>
</ul>

<h2>3. What We DON'T Collect</h2>
<p>We explicitly do NOT collect:</p>
<ul>
<li>Passwords or authentication tokens</li>
<li>Direct messages or private communication</li>
<li>Payment information</li>
<li>Location data</li>
<li>Browsing history outside Discord</li>
<li>Biometric data</li>
<li>Sensitive personal information</li>
</ul>

<h2>4. How We Use Your Data</h2>
<p>We use your data to:</p>
<ul>
<li><strong>Maintain vouch records</strong> - Core functionality</li>
<li><strong>Calculate leaderboards</strong> - Ranking and statistics</li>
<li><strong>Generate threat scores</strong> - Behavioral analysis for server safety</li>
<li><strong>Audit trails</strong> - Track who modified what and when</li>
<li><strong>Service improvement</strong> - Fix bugs, optimize performance</li>
<li><strong>Compliance</strong> - Prevent abuse and enforce Terms of Service</li>
</ul>

<h2>5. Data Storage & Security</h2>
<h3 style="font-size:16px;margin-top:15px">Where Data is Stored</h3>
<ul>
<li><strong>Primary:</strong> JSON file on deployment server (Railway)</li>
<li><strong>Backup:</strong> Encrypted backups if configured</li>
<li><strong>Not cloud:</strong> Data is not replicated to unknown cloud services</li>
</ul>

<h3 style="font-size:16px;margin-top:15px">Security Measures</h3>
<ul>
<li><strong>File permissions:</strong> Restricted access to data files</li>
<li><strong>Encryption in transit:</strong> HTTPS for all dashboard connections</li>
<li><strong>No public access:</strong> Data is not publicly accessible</li>
<li><strong>Admin-only access:</strong> Only server admins can view/modify</li>
</ul>

<h2>6. Your Rights</h2>
<p>You have the right to:</p>
<ul>
<li><strong>Access:</strong> Ask your admin for your data</li>
<li><strong>Correct:</strong> Request inaccurate data be fixed</li>
<li><strong>Delete:</strong> Request your data be removed</li>
<li><strong>Port:</strong> Get your data in a readable format</li>
<li><strong>Object:</strong> Challenge how your data is used</li>
</ul>

<h2>7. Contact</h2>
<p>For privacy questions, contact the bot developers via <a href="https://github.com/Yuki-Onnaa/Pve-Bot">GitHub</a>.</p>

<p><strong>By using Pve-Bot, you accept this Privacy Policy.</strong></p>
</div>
</body>
</html>"""
    return html

@app.route("/")
@member_required
def index():
    tab = request.args.get("tab", "announcements")
    viewing_uid = request.args.get("uid", "")
    viewing_name = ""
    if viewing_uid and str(viewing_uid).isdigit() and str(viewing_uid) != str(session["user"]["id"]):
        viewing_name = resolve_user(viewing_uid)["name"]
    else:
        viewing_uid = ""
    record_visit(session["user"]["id"], tab if tab in PUBLIC_SITE_TABS else "announcements")
    return render_template_string(
        PUBLIC_HTML, user=session["user"], is_admin=is_admin(),
        initial_tab=tab if tab in PUBLIC_SITE_TABS else "announcements",
        viewing_uid=viewing_uid, viewing_name=viewing_name,
    )


@app.route("/dashboard")
@admin_required
def dashboard_page():
    record_visit(session["user"]["id"], "dashboard")
    return render_template_string(DASHBOARD_HTML)


@app.route("/profile")
@member_required
def profile_page():
    return redirect("/?tab=profile")


@app.route("/api/profile")
@member_required
def api_profile():
    return jsonify(build_profile(str(session["user"]["id"]), own=True))


@app.route("/api/profile/notification_prefs", methods=["POST"])
@member_required
def api_profile_notification_prefs():
    body = request.json or {}
    uid = str(session["user"]["id"])
    with data_txn() as data:
        record = data.setdefault(uid, {})
        if "streak_dm_opt_out" in body:
            record["streak_dm_opt_out"] = bool(body["streak_dm_opt_out"])
        if "rank_up_dm_opt_out" in body:
            record["rank_up_dm_opt_out"] = bool(body["rank_up_dm_opt_out"])
    return jsonify({
        "ok": True,
        "streak_dm_opt_out": bool(record.get("streak_dm_opt_out")),
        "rank_up_dm_opt_out": bool(record.get("rank_up_dm_opt_out")),
    })


@app.route("/api/profile/<uid>")
@member_required
def api_member_profile(uid):
    """Someone else's profile. Same shape, minus anything private."""
    if not str(uid).isdigit():
        return jsonify({"error": "Unknown member"}), 404
    data = load_data()
    if uid not in data:
        return jsonify({"error": "That member has no vouches yet."}), 404
    return jsonify(build_profile(str(uid), own=False))


def build_profile(uid, own=True):
    data = load_data()
    record = data.get(uid, {})
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).isoformat()
    prev_start = (now - timedelta(days=14)).isoformat()

    categories = []
    recent = []
    this_week = 0.0
    last_week = 0.0

    economy = get_economy(data)
    days = 30
    today = now.date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    day_index = {d: i for i, d in enumerate(labels)}
    series = {}

    for cat in ALL_CATEGORIES:
        cat_rec = record.get(cat) or {}
        points = cat_rec.get("total_points", 0)
        vouches = cat_rec.get("total_vouches", 0)
        metric = (_bridge["metric"] or {}).get(cat, "points")
        value = vouches if metric == "vouches" else points

        # leaderboard position and the people either side of you
        board = sorted(
            ((uid2, r.get(cat, {}).get("total_points", 0)) for uid2, r in user_records(data)),
            key=lambda kv: kv[1], reverse=True,
        )
        board = [row for row in board if row[1] > 0]
        ranked = [p for _, p in board]
        position = None
        rivals = {"above": None, "below": None}
        for i, (uid2, pts) in enumerate(board):
            if uid2 == uid:
                position = i + 1
                if i > 0:
                    who2 = resolve_user(board[i - 1][0])
                    rivals["above"] = {"uid": board[i - 1][0], "name": who2["name"],
                                       "gap": round(board[i - 1][1] - pts, 1)}
                if i + 1 < len(board):
                    who2 = resolve_user(board[i + 1][0])
                    rivals["below"] = {"uid": board[i + 1][0], "name": who2["name"],
                                       "gap": round(pts - board[i + 1][1], 1)}
                break

        # every rank still ahead of you, and what it would take
        ladder = economy["ranks"].get(cat) or []
        events = economy["events"].get(cat) or {}
        preferred = [n for n in GOAL_ROUTE_EVENTS.get(cat, []) if events.get(n, 0) > 0]
        fallback = [n for _, n in sorted(((p, n) for n, p in events.items() if p > 0), reverse=True)
                    if n not in preferred]
        best = [(events[n], n) for n in (preferred + fallback)[:4]]
        goals = []
        for at, role_name in ladder:
            if at <= value:
                continue
            short = round(at - value, 1)
            if metric == "vouches":
                routes = [{"event": "any vouch", "need": int(short) + (1 if short % 1 else 0)}]
            else:
                routes = [{"event": n, "need": int(-(-short // p))} for p, n in best]
            goals.append({"role": role_name, "at": at, "short": short, "routes": routes})

        # daily points for the chart
        daily = [0.0] * days
        for entry in cat_rec.get("log", []):
            day = str(entry.get("time", ""))[:10]
            if day in day_index:
                daily[day_index[day]] += float(entry.get("points", 0) or 0)
        series[cat] = [round(v, 1) for v in daily]

        for entry in cat_rec.get("log", []):
            when = entry.get("time", "")
            pts = float(entry.get("points", 0) or 0)
            if when >= week_start:
                this_week += pts
            elif when >= prev_start:
                last_week += pts
            recent.append({
                "category": cat, "category_name": CATEGORY_NAMES[cat],
                "event": entry.get("event", ""), "points": pts,
                "time": when, "by": entry.get("by_name") or "",
            })

        categories.append({
            "key": cat,
            "name": CATEGORY_NAMES[cat],
            "points": round(points, 1),
            "vouches": vouches,
            "metric": metric,
            "position": position,
            "of": len(ranked),
            "rivals": rivals,
            "goals": goals,
            "rank": rank_progress(cat, points, vouches, data),
            "events": {k: v for k, v in (cat_rec.get("events") or {}).items() if v > 0},
        })

    recent.sort(key=lambda e: e["time"], reverse=True)

    # personal bests, from the same log entries
    by_day = {}
    for e in recent:
        by_day[e["time"][:10]] = by_day.get(e["time"][:10], 0) + e["points"]
    best_day = max(by_day.items(), key=lambda kv: kv[1]) if by_day else None
    active_days = len(by_day)
    first_seen = min((e["time"] for e in recent), default="")
    last_vouch = {"event": recent[0]["event"], "time": recent[0]["time"]} if recent else None

    who = resolve_user(uid)
    if own:
        person = dict(session["user"])
    else:
        person = {"id": uid, "username": who["name"], "handle": "", "avatar": who["avatar"]}

    return {
        "own": own,
        "user": person,
        "resolved": who["resolved"],
        "total": round(combined_total(record), 1),
        "categories": categories,
        "recent": recent[:20],
        "this_week": round(this_week, 1),
        "last_week": round(last_week, 1),
        "has_data": bool(record),
        "chart": {"labels": labels, "series": series},
        "streak": host_streak_stats(record),
        "badges": host_badges(record),
        "streak_dm_opt_out": bool(record.get("streak_dm_opt_out")) if own else None,
        "rank_up_dm_opt_out": bool(record.get("rank_up_dm_opt_out")) if own else None,
        "last_vouch": last_vouch,
        "bests": {
            "best_day": {"date": best_day[0], "points": round(best_day[1], 1)} if best_day else None,
            "active_days": active_days,
            "first_seen": first_seen[:10],
            "total_vouches": sum(c["vouches"] for c in categories),
        },
    }


def host_streak_stats(record):
    """Consecutive /host runs, each within 24h of the previous one (rolling window, not calendar days)."""
    times = []
    for iso in record.get("host_runs", []):
        try:
            times.append(datetime.fromisoformat(str(iso)))
        except (ValueError, TypeError):
            continue
    times.sort()

    longest = 0
    run = 0
    prev = None
    for t in times:
        run = run + 1 if prev is not None and (t - prev).total_seconds() <= 24 * 3600 else 1
        longest = max(longest, run)
        prev = t

    last_at = times[-1] if times else None
    now = datetime.now(timezone.utc)
    if last_at is None:
        current, at_risk, hours_left = 0, False, 0
    else:
        seconds_since = (now - last_at).total_seconds()
        if seconds_since <= 24 * 3600:
            current = run
            at_risk = seconds_since >= 20 * 3600  # heads-up in the last 4 hours
            hours_left = max(0, round(24 - seconds_since / 3600))
        else:
            current, at_risk, hours_left = 0, False, 0

    return {
        "current": current,
        "longest": longest,
        "at_risk": at_risk,
        "hours_left": hours_left,
        "last_at": last_at.isoformat() if last_at else None,
        "total_runs": len(times),
    }


def _own_history(uid, args):
    """Every vouch this member has received, newest first, with filters applied."""
    data = load_data()
    record = data.get(str(uid), {})
    category = args.get("category", "")
    q = args.get("q", "").lower().strip()
    try:
        days = int(args.get("days", 0))
    except (ValueError, TypeError):
        days = 0
    cutoff = ""
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    rows = []
    for cat in ALL_CATEGORIES:
        if category and cat != category:
            continue
        for e in (record.get(cat) or {}).get("log", []):
            when = e.get("time", "")
            if cutoff and when < cutoff:
                continue
            event = str(e.get("event", ""))
            by = e.get("by_name") or ""
            if q and q not in event.lower() and q not in by.lower():
                continue
            rows.append({
                "category": cat, "category_name": CATEGORY_NAMES[cat], "event": event,
                "points": float(e.get("points", 0) or 0), "count": e.get("count", 1),
                "by": by, "time": when, "backfilled": e.get("backfilled", False),
            })
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows


@app.route("/members")
@member_required
def members_page():
    return redirect("/?tab=members")


@app.route("/api/members")
@member_required
def api_members():
    """Everyone with at least one vouch, for the member directory."""
    data = load_data()
    me = str(session["user"]["id"])
    rows = []
    for uid, rec in user_records(data):
        totals = {cat: round(rec.get(cat, {}).get("total_points", 0), 1) for cat in ALL_CATEGORIES}
        vouches = sum(rec.get(cat, {}).get("total_vouches", 0) for cat in ALL_CATEGORIES)
        total = round(combined_total(rec), 1)
        if total <= 0 and vouches <= 0:
            continue

        top_cat = max(totals, key=lambda c: totals[c])
        rank = None
        if totals[top_cat] > 0:
            progress = rank_progress(top_cat, totals[top_cat],
                                     rec.get(top_cat, {}).get("total_vouches", 0), data)
            if progress and progress.get("current"):
                rank = {"name": progress["current"], "category": CATEGORY_NAMES[top_cat]}

        who = resolve_user(uid)
        rows.append({
            "uid": uid, "name": who["name"], "avatar": who["avatar"], "resolved": who["resolved"],
            "total": total, "vouches": vouches, "totals": totals, "rank": rank,
            "is_me": uid == me, "badge": top_host_badge(rec),
        })

    rows.sort(key=lambda r: r["total"], reverse=True)
    for i, row in enumerate(rows):
        row["position"] = i + 1
    return jsonify({"members": rows[:500], "count": len(rows)})


@app.route("/api/givers")
@member_required
def api_givers():
    """Who hands out the most vouches, from the by field on every log entry."""
    try:
        days = int(request.args.get("days", 0))
    except (ValueError, TypeError):
        days = 0
    cutoff = ""
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Only Host vouches count towards this board.
    category = request.args.get("category", "pve")
    cats = ALL_CATEGORIES if category == "all" else [category if category in ALL_CATEGORIES else "pve"]

    givers = {}
    for uid, rec in user_records(load_data()):
        for cat in cats:
            for entry in (rec.get(cat) or {}).get("log", []):
                when = entry.get("time", "")
                if cutoff and when < cutoff:
                    continue

                by = (entry.get("by") or "").strip()
                by_name = (entry.get("by_name") or "").strip()
                # older entries recorded a label rather than a user id
                key = by if by.isdigit() else (by_name or by or "unknown")

                slot = givers.setdefault(key, {
                    "uid": by if by.isdigit() else "",
                    "label": by_name or ("Unknown" if not by else by),
                    "given": 0, "points": 0.0, "recipients": set(),
                    "categories": {c: 0 for c in ALL_CATEGORIES}, "last": "",
                })
                count_val = entry.get("count")
                count_val = int(count_val) if count_val not in (None, "") else 1
                slot["given"] += count_val
                slot["points"] += float(entry.get("points", 0) or 0)
                slot["categories"][cat] += count_val
                slot["recipients"].add(uid)
                if when > slot["last"]:
                    slot["last"] = when

    rows = []
    for slot in givers.values():
        who = resolve_user(slot["uid"]) if slot["uid"] else None
        rows.append({
            "uid": slot["uid"],
            "name": who["name"] if who and who["resolved"] else slot["label"],
            "avatar": who["avatar"] if who else "",
            "resolved": bool(who and who["resolved"]),
            "given": slot["given"],
            "points": round(slot["points"], 1),
            "people": len(slot["recipients"]),
            "categories": slot["categories"],
            "last": slot["last"],
        })

    rows.sort(key=lambda r: r["given"], reverse=True)
    for i, row in enumerate(rows):
        row["position"] = i + 1
    return jsonify({
        "givers": rows[:200],
        "count": len(rows),
        "total_given": sum(r["given"] for r in rows),
        "category": category,
        "category_name": "all categories" if category == "all" else CATEGORY_NAMES.get(cats[0], "Host"),
    })


@app.route("/u/<uid>")
@member_required
def public_profile_page(uid):
    if not str(uid).isdigit() or str(uid) == str(session["user"]["id"]):
        return redirect("/?tab=profile")
    return redirect("/?tab=profile&uid=" + str(uid))


@app.route("/api/profile/history")
@member_required
def api_profile_history():
    rows = _own_history(session["user"]["id"], request.args)
    return jsonify({"rows": rows[:500], "total": len(rows),
                    "points": round(sum(r["points"] for r in rows), 1)})


@app.route("/api/profile/history.csv")
@member_required
def api_profile_history_csv():
    rows = _own_history(session["user"]["id"], request.args)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "category", "event", "points", "count", "given_by", "backfilled"])
    for r in rows:
        writer.writerow([r["time"], r["category_name"], r["event"], r["points"],
                         r["count"], r["by"], "yes" if r["backfilled"] else "no"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=my-vouches-{stamp}.csv"})

# ── API: Session ──

@app.route("/api/me")
@admin_required
def api_me():
    # Only one guild's data ever backs this dashboard (one shared DATA_FILE, no
    # per-guild scoping anywhere) - this is display info, not a switcher.
    guilds = session.get("admin_guilds", [])
    return jsonify({"user": session["user"], "guild": guilds[0] if guilds else None})

# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

# ── API: Status ──

@app.route("/api/status")
@admin_required
def api_status():
    data = load_data()
    settings = data.get("_settings", {})
    config = {**DEFAULT_CONFIG, **data.get("_config", {})}
    total_users = sum(1 for uid in data if uid.isdigit())
    total_vouches = sum(
        rec.get(cat, {}).get("total_vouches", 0)
        for uid, rec in user_records(data)
        for cat in ALL_CATEGORIES
    )
    return jsonify({
        "chat_enabled": settings.get("chat_enabled", True),
        "persona": settings.get("persona", "default"),
        "memory_count": len(data.get("_memories", [])),
        "user_count": total_users,
        "total_vouches": total_vouches,
        "config": config,
    })

# ── API: Server pulse ──

@app.route("/api/pulse")
@member_required
def api_pulse():
    """A public snapshot of how active the server's been - real aggregates
    from the same vouch log entries and ticket data everything else uses."""
    data = load_data()
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).isoformat()

    total_members = sum(1 for uid in data if uid.isdigit())
    total_vouches_all_time = 0
    vouches_this_week = 0
    points_this_week = 0.0
    host_points_week = {}
    voucher_counts_week = {}

    for uid, rec in user_records(data):
        for cat in ALL_CATEGORIES:
            cat_rec = rec.get(cat) or {}
            total_vouches_all_time += cat_rec.get("total_vouches", 0)
            for entry in cat_rec.get("log", []):
                when = entry.get("time", "")
                if when < week_start:
                    continue
                vouches_this_week += 1
                pts = float(entry.get("points", 0) or 0)
                points_this_week += pts
                if cat == "pve":
                    host_points_week[uid] = host_points_week.get(uid, 0) + pts
                by = (entry.get("by") or "").strip()
                if by.isdigit():
                    voucher_counts_week[by] = voucher_counts_week.get(by, 0) + 1

    top_host = max(host_points_week.items(), key=lambda kv: kv[1], default=(None, 0))
    top_voucher = max(voucher_counts_week.items(), key=lambda kv: kv[1], default=(None, 0))

    live_count = sum(
        1 for _, rec in user_records(data)
        if (rec.get("last_host") or {}).get("stage_channel_id") and not (rec.get("last_host") or {}).get("ended")
    )
    open_tickets = len(data.get("_tickets", {}))

    return jsonify({
        "total_members": total_members,
        "total_vouches_all_time": total_vouches_all_time,
        "vouches_this_week": vouches_this_week,
        "points_this_week": round(points_this_week, 1),
        "top_host_week": {"uid": top_host[0], **resolve_user(top_host[0]), "points": round(top_host[1], 1)}
            if top_host[0] else None,
        "top_voucher_week": {"uid": top_voucher[0], **resolve_user(top_voucher[0]), "count": top_voucher[1]}
            if top_voucher[0] else None,
        "live_now_count": live_count,
        "open_tickets": open_tickets,
    })

# ── API: Live now ──

@app.route("/api/live_now")
@member_required
def api_live_now():
    """Currently-live hosted events, derived from each host's last_host tracking
    (the same tracking /host, /end, and on_stage_instance_delete keep in sync)."""
    data = load_data()
    bot = _bridge["bot"]
    live = []
    for uid, rec in user_records(data):
        last_host = rec.get("last_host")
        if not last_host or last_host.get("ended") or not last_host.get("stage_channel_id"):
            continue
        host_runs = rec.get("host_runs") or []
        stage_name = None
        if bot is not None:
            try:
                channel = bot.get_channel(int(last_host["stage_channel_id"]))
                stage_name = getattr(channel, "name", None)
            except (ValueError, TypeError):
                pass
        who = resolve_user(uid)
        co_hosts = [resolve_user(cid)["name"] for cid in (last_host.get("co_host_ids") or [])]
        live.append({
            "uid": uid, "host": who["name"], "host_avatar": who["avatar"],
            "co_hosts": co_hosts,
            "event": last_host.get("event", ""),
            "stage": stage_name,
            "started_at": host_runs[-1] if host_runs else None,
        })
    live.sort(key=lambda x: x["started_at"] or "", reverse=True)
    return jsonify(live)

# ── API: Leaderboard ──

@app.route("/api/leaderboard")
@member_required
def api_leaderboard():
    data = load_data()
    result = {}
    for cat in ALL_CATEGORIES:
        ranked = sorted(
            user_records(data),
            key=lambda kv: kv[1].get(cat, {}).get("total_points", 0),
            reverse=True,
        )
        ranked = [(uid, rec) for uid, rec in ranked if rec.get(cat, {}).get("total_points", 0) > 0][:25]
        result[cat] = [
            {"uid": uid, "points": rec[cat]["total_points"], "vouches": rec[cat]["total_vouches"],
             **resolve_user(uid)}
            for uid, rec in ranked
        ]
    return jsonify(result)

# ── API: Users ──

@app.route("/api/users")
@admin_required
def api_users():
    data = load_data()
    q = request.args.get("q", "").lower()
    users = []
    for uid, rec in user_records(data):
        if q and q not in uid and q not in resolve_user(uid)["name"].lower():
            continue
        users.append({
            "uid": uid,
            **resolve_user(uid),
            "total": combined_total(rec),
            "pve": rec.get("pve", {}).get("total_points", 0),
            "security": rec.get("security", {}).get("total_points", 0),
            "support": rec.get("support", {}).get("total_points", 0),
        })
    users.sort(key=lambda u: u["total"], reverse=True)
    return jsonify(users[:100])

@app.route("/api/users/<uid>")
@admin_required
def api_user_detail(uid):
    if not uid.isdigit():
        return jsonify({"error": "Invalid user ID"}), 400
    data = load_data()
    rec = data.get(uid, {})
    result = {"uid": uid, "total": combined_total(rec), "categories": {}, **resolve_user(uid)}
    for cat in ALL_CATEGORIES:
        cat_rec = rec.get(cat, {})
        log = cat_rec.get("log", [])
        result["categories"][cat] = {
            "total_points": cat_rec.get("total_points", 0),
            "total_vouches": cat_rec.get("total_vouches", 0),
            "rank": rank_progress(cat, cat_rec.get("total_points", 0), cat_rec.get("total_vouches", 0)),
            "events": cat_rec.get("events", {}),
            "log": [
                {**e, "idx_id": f"idx{i}" if not e.get("id") else e.get("id")}
                for i, e in enumerate(log[-20:])
            ],
        }
    return jsonify(result)

# ── API: Vouches ──

@app.route("/api/vouches/add", methods=["POST"])
@admin_required
def api_add_vouch():
    body = request.json or {}
    uid = (body.get("uid") or "").strip()
    category = body.get("category", "")
    event_name = body.get("event_name", "")
    try:
        count = max(1, int(body.get("count", 1)))
    except (ValueError, TypeError):
        count = 1

    if not uid.isdigit():
        return jsonify({"error": "Invalid user ID"}), 400
    if category not in ALL_CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400

    with data_txn() as data:
        economy = get_economy(data)
        if event_name not in economy["events"].get(category, {}):
            return jsonify({"error": f"Invalid event for {category}"}), 400

        points = economy["events"][category][event_name]
        record = ensure_user_cat(data, uid, category)
        record["total_points"] += points * count
        record["total_vouches"] += count
        record["events"][event_name] = record["events"].get(event_name, 0) + count
        actor = session.get("user", {})
        record["log"].append({
            "id": uuid.uuid4().hex[:8],
            "by": actor.get("id", "dashboard"),
            "by_name": actor.get("username", "Dashboard"),
            "event": event_name,
            "points": points * count,
            "count": count,
            "backfilled": True,
            "time": datetime.now(timezone.utc).isoformat(),
        })
        new_total = record["total_points"]
    return jsonify({"ok": True, "new_total": new_total})

@app.route("/api/vouches/revert", methods=["POST"])
@admin_required
def api_revert_vouch():
    body = request.json or {}
    uid = (body.get("uid") or "").strip()
    category = body.get("category", "")
    log_id = (body.get("log_id") or "").strip()

    if not uid.isdigit() or category not in CATEGORY_EVENTS:
        return jsonify({"error": "Invalid uid or category"}), 400

    with data_txn() as data:
        record = data.get(uid, {}).get(category)
        if not record:
            return jsonify({"error": "No record found for this user/category"}), 404

        entry = None
        entry_index = None
        for i, e in enumerate(record["log"]):
            ref = e.get("id") or f"idx{i}"
            if ref == log_id:
                entry = e
                entry_index = i
                break

        if entry is None:
            return jsonify({"error": "Log entry not found"}), 404

        points = entry.get("points", 0)
        count = entry.get("count", 1)
        event_name = entry.get("event", "")
        record["total_points"] = max(0, record["total_points"] - points)
        record["total_vouches"] = max(0, record["total_vouches"] - count)
        record["events"][event_name] = max(0, record["events"].get(event_name, 0) - count)
        del record["log"][entry_index]
        new_total = record["total_points"]
    return jsonify({"ok": True, "new_total": new_total})

@app.route("/api/vouches/delete_user", methods=["POST"])
@admin_required
def api_delete_user():
    body = request.json or {}
    uid = (body.get("uid") or "").strip()
    category = body.get("category", None)
    if not uid.isdigit():
        return jsonify({"error": "Invalid user ID"}), 400
    with data_txn() as data:
        if uid not in data:
            return jsonify({"error": "User not found"}), 404
        if category:
            if category in data[uid]:
                del data[uid][category]
        else:
            del data[uid]
    return jsonify({"ok": True})

# ── API: Memories ──

@app.route("/api/memories", methods=["GET"])
@admin_required
def api_memories_get():
    data = load_data()
    return jsonify(data.get("_memories", []))

@app.route("/api/memories", methods=["POST"])
@admin_required
def api_memories_add():
    body = request.json or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text required"}), 400
    with data_txn() as data:
        memories = data.get("_memories", [])
        memories.append({
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "added_by": session.get("user", {}).get("username", "dashboard"),
            "time": datetime.now(timezone.utc).isoformat(),
        })
        data["_memories"] = memories[-50:]
    return jsonify({"ok": True})

@app.route("/api/memories/<memory_id>", methods=["DELETE"])
@admin_required
def api_memories_delete(memory_id):
    with data_txn() as data:
        memories = data.get("_memories", [])
        new_m = [m for m in memories if m["id"] != memory_id]
        if len(new_m) == len(memories):
            return jsonify({"error": "Not found"}), 404
        data["_memories"] = new_m
    return jsonify({"ok": True})

# ── API: Ticket mods (roles granted ticket access, on top of Manage Server) ──

@app.route("/api/ticket_mods", methods=["GET"])
@admin_required
def api_ticket_mods_get():
    data = load_data()
    return jsonify(data.get("_ticket_mod_roles", []))

@app.route("/api/ticket_mods", methods=["POST"])
@admin_required
def api_ticket_mods_add():
    body = request.json or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Role name is required."}), 400
    with data_txn() as data:
        roles = data.get("_ticket_mod_roles", [])
        if any(r["name"].lower() == name.lower() for r in roles):
            return jsonify({"error": "That role is already a ticket mod."}), 400
        roles.append({"id": uuid.uuid4().hex[:8], "name": name})
        data["_ticket_mod_roles"] = roles
    return jsonify({"ok": True})

@app.route("/api/ticket_mods/<mod_id>", methods=["DELETE"])
@admin_required
def api_ticket_mods_delete(mod_id):
    with data_txn() as data:
        roles = data.get("_ticket_mod_roles", [])
        new_roles = [r for r in roles if r["id"] != mod_id]
        if len(new_roles) == len(roles):
            return jsonify({"error": "Not found"}), 404
        data["_ticket_mod_roles"] = new_roles
    return jsonify({"ok": True})

# ── API: Anti-nuke whitelist (people exempt from the anti-nuke detector) ──

@app.route("/api/antinuke_whitelist", methods=["GET"])
@whitelist_manager_required
def api_antinuke_whitelist_get():
    data = load_data()
    return jsonify(data.get("_antinuke_whitelist", []))

@app.route("/api/antinuke_whitelist", methods=["POST"])
@whitelist_manager_required
def api_antinuke_whitelist_add():
    body = request.json or {}
    user_id = (body.get("id") or "").strip()
    name = (body.get("name") or "").strip()
    if not user_id.isdigit():
        return jsonify({"error": "A valid Discord user ID is required."}), 400
    with data_txn() as data:
        entries = data.get("_antinuke_whitelist", [])
        if any(e["id"] == user_id for e in entries):
            return jsonify({"error": "That user is already whitelisted."}), 400
        entries.append({
            "id": user_id,
            "name": name or user_id,
            "added_by": session.get("user", {}).get("username", "dashboard"),
            "time": datetime.now(timezone.utc).isoformat(),
        })
        data["_antinuke_whitelist"] = entries
    return jsonify({"ok": True})

@app.route("/api/antinuke_whitelist/<user_id>", methods=["DELETE"])
@whitelist_manager_required
def api_antinuke_whitelist_delete(user_id):
    with data_txn() as data:
        entries = data.get("_antinuke_whitelist", [])
        new_entries = [e for e in entries if e["id"] != user_id]
        if len(new_entries) == len(entries):
            return jsonify({"error": "Not found"}), 404
        data["_antinuke_whitelist"] = new_entries
    return jsonify({"ok": True})

# ── API: Role grants (anyone holding a granter role can grant exactly one target role via /giverole) ──

@app.route("/api/role_grants", methods=["GET"])
@admin_required
def api_role_grants_get():
    data = load_data()
    return jsonify(data.get("_role_grants", []))

@app.route("/api/role_grants", methods=["POST"])
@admin_required
def api_role_grants_add():
    body = request.json or {}
    granter_role_name = (body.get("granter_role_name") or "").strip()
    role_name = (body.get("role_name") or "").strip()
    if not granter_role_name:
        return jsonify({"error": "A granter role name is required."}), 400
    if not role_name:
        return jsonify({"error": "A role name to grant is required."}), 400
    with data_txn() as data:
        entries = data.get("_role_grants", [])
        entries.append({
            "id": uuid.uuid4().hex[:8],
            "granter_role_name": granter_role_name,
            "role_name": role_name,
            "added_by": session.get("user", {}).get("username", "dashboard"),
            "time": datetime.now(timezone.utc).isoformat(),
        })
        data["_role_grants"] = entries
    return jsonify({"ok": True})

@app.route("/api/role_grants/<grant_id>", methods=["DELETE"])
@admin_required
def api_role_grants_delete(grant_id):
    with data_txn() as data:
        entries = data.get("_role_grants", [])
        new_entries = [e for e in entries if e["id"] != grant_id]
        if len(new_entries) == len(entries):
            return jsonify({"error": "Not found"}), 404
        data["_role_grants"] = new_entries
    return jsonify({"ok": True})

# ── API: Bot updates (posted to the updates channel, editable after the fact) ──

DISCORD_MESSAGE_LIMIT = 4096  # embed description limit

@app.route("/api/updates", methods=["GET"])
@admin_required
def api_updates_get():
    data = load_data()
    updates = sorted(data.get("_bot_updates", []), key=lambda u: u.get("posted_at", ""), reverse=True)
    return jsonify(updates)

@app.route("/api/announcements", methods=["GET"])
@member_required
def api_announcements():
    """Public read-only view of bot updates - same data as /api/updates, admin fields dropped."""
    data = load_data()
    updates = sorted(data.get("_bot_updates", []), key=lambda u: u.get("posted_at", ""), reverse=True)
    return jsonify([
        {"id": u["id"], "content": u["content"], "posted_by": u.get("posted_by", ""),
         "posted_at": u.get("posted_at", ""), "edited_at": u.get("edited_at")}
        for u in updates
    ])

@app.route("/api/updates", methods=["POST"])
@admin_required
def api_updates_post():
    body = request.json or {}
    content = (body.get("content") or "").strip()
    if not content:
        return jsonify({"error": "Message text is required."}), 400
    if len(content) > DISCORD_MESSAGE_LIMIT:
        return jsonify({"error": f"Message is too long ({DISCORD_MESSAGE_LIMIT} character limit)."}), 400
    if _bridge.get("bot") is None or _bridge.get("loop") is None:
        return jsonify({"error": "Bot isn't connected yet. Try again once it's online."}), 503

    data = load_data()
    config = {**DEFAULT_CONFIG, **data.get("_config", {})}
    channel_id = int(config.get("updates_channel_id") or 0)
    posted_by = session.get("user", {}).get("username", "dashboard")
    posted_at = datetime.now(timezone.utc).isoformat()

    try:
        future = run_on_bot(_post_update_message(channel_id, content, posted_by, posted_at))
        message_id = future.result(timeout=30)
    except Exception as exc:
        return jsonify({"error": f"Could not post to Discord: {exc}"}), 500

    record = {
        "id": uuid.uuid4().hex[:8],
        "channel_id": str(channel_id),
        "message_id": message_id,
        "content": content,
        "posted_by": posted_by,
        "posted_at": posted_at,
        "edited_at": None,
    }
    # Re-read right before saving - `data` was captured before the (up to 30s)
    # blocking call to post on Discord above, so anything else could have saved
    # its own changes in the meantime. Can't hold the shared lock across that
    # call either, since it would stall every other reader/writer, bot included.
    data = load_data()
    updates = data.get("_bot_updates", [])
    updates.append(record)
    data["_bot_updates"] = updates[-200:]
    save_data(data)
    return jsonify({"ok": True, "update": record})

@app.route("/api/updates/<update_id>", methods=["POST"])
@admin_required
def api_updates_edit(update_id):
    body = request.json or {}
    content = (body.get("content") or "").strip()
    if not content:
        return jsonify({"error": "Message text is required."}), 400
    if len(content) > DISCORD_MESSAGE_LIMIT:
        return jsonify({"error": f"Message is too long ({DISCORD_MESSAGE_LIMIT} character limit)."}), 400

    data = load_data()
    updates = data.get("_bot_updates", [])
    record = next((u for u in updates if u["id"] == update_id), None)
    if record is None:
        return jsonify({"error": "Not found"}), 404
    if _bridge.get("bot") is None or _bridge.get("loop") is None:
        return jsonify({"error": "Bot isn't connected yet. Try again once it's online."}), 503

    try:
        future = run_on_bot(_edit_update_message(
            int(record["channel_id"]), record["message_id"], content,
            record["posted_by"], record["posted_at"]))
        future.result(timeout=30)
    except Exception as exc:
        return jsonify({"error": f"Could not edit the Discord message: {exc}"}), 500

    # Re-read and re-locate the record right before saving - `data`/`record` were
    # captured before the blocking Discord edit call above, so we can't just
    # write the stale snapshot back without risking clobbering another write
    # that landed in the meantime.
    data = load_data()
    updates = data.get("_bot_updates", [])
    record = next((u for u in updates if u["id"] == update_id), None)
    if record is None:
        return jsonify({"error": "Not found"}), 404
    record["content"] = content
    record["edited_at"] = datetime.now(timezone.utc).isoformat()
    data["_bot_updates"] = updates
    save_data(data)
    return jsonify({"ok": True, "update": record})

# ── API: Settings ──

@app.route("/api/settings", methods=["GET"])
@admin_required
def api_settings_get():
    data = load_data()
    config = {**DEFAULT_CONFIG, **data.get("_config", {})}
    return jsonify({
        "chat_enabled": data.get("_settings", {}).get("chat_enabled", True),
        "persona": data.get("_settings", {}).get("persona", "default"),
        "config": config,
        "personas": PERSONAS,
    })

@app.route("/api/settings", methods=["POST"])
@admin_required
def api_settings_update():
    body = request.json or {}
    with data_txn() as data:
        settings = data.setdefault("_settings", {})
        cfg = data.setdefault("_config", {})

        if "chat_enabled" in body:
            settings["chat_enabled"] = bool(body["chat_enabled"])
        if "persona" in body and body["persona"] in PERSONAS:
            settings["persona"] = body["persona"]

        channel_keys = [
            "pve_channel_id", "security_channel_id", "support_channel_id",
            "live_leaderboard_channel_id", "audit_log_channel_id",
            "event_ping_channel_id", "chime_in_channel_id", "updates_channel_id",
            "on_leave_button_channel_id", "on_leave_log_channel_id",
        ]
        for key in channel_keys:
            if key in body:
                try:
                    cfg[key] = int(body[key])
                except (ValueError, TypeError):
                    pass

    return jsonify({"ok": True})

# ── API: On Leave ──

@app.route("/api/on_leave", methods=["GET"])
@admin_required
def api_on_leave():
    data = load_data()
    logs = data.get("_on_leave_logs", [])

    last_by_user = {}
    for entry in logs:
        last_by_user[entry.get("user_id")] = entry
    current = [e for e in last_by_user.values() if e.get("action") == "start"]
    current.sort(key=lambda e: e.get("time", ""), reverse=True)

    history = sorted(logs, key=lambda e: e.get("time", ""), reverse=True)[:200]
    return jsonify({"current": current, "history": history})

# ── API: Audit Log ──

def _collect_audit(args):
    """Flatten every log entry, newest first, applying the given filters."""
    data = load_data()
    category = args.get("category", "")
    uid_filter = (args.get("uid") or "").strip()
    q = args.get("q", "").lower().strip()
    try:
        days = int(args.get("days", 0))
    except (ValueError, TypeError):
        days = 0
    cutoff = ""
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    entries = []
    for uid, rec in user_records(data):
        if uid_filter and uid_filter not in uid:
            continue
        for cat in ALL_CATEGORIES:
            if category and cat != category:
                continue
            for i, e in enumerate(rec.get(cat, {}).get("log", [])):
                when = e.get("time", "")
                if cutoff and when < cutoff:
                    continue
                who = resolve_user(uid)
                by_name = e.get("by_name") or str(e.get("by", ""))
                if q and q not in str(e.get("event", "")).lower() and q not in by_name.lower() \
                        and q not in who["name"].lower() and q not in uid:
                    continue
                entries.append({
                    "uid": uid, "name": who["name"], "avatar": who["avatar"],
                    "category": cat, "event": e.get("event"), "points": e.get("points"),
                    "by": by_name, "time": when, "backfilled": e.get("backfilled", False),
                    "id": e.get("id") or f"idx{i}",
                })
    entries.sort(key=lambda e: e.get("time") or "", reverse=True)
    return entries

@app.route("/api/auditlog")
@admin_required
def api_auditlog():
    return jsonify(_collect_audit(request.args)[:400])

@app.route("/api/auditlog.csv")
@admin_required
def api_auditlog_csv():
    entries = _collect_audit(request.args)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "category", "event", "points", "user_id", "user_name", "given_by", "backfilled"])
    for e in entries:
        writer.writerow([e["time"], CATEGORY_NAMES.get(e["category"], e["category"]), e["event"],
                         e["points"], e["uid"], e["name"], e["by"], "yes" if e["backfilled"] else "no"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit-log-{stamp}.csv"},
    )

# ── API: Points over time (chart) ──

@app.route("/api/points_over_time")
@admin_required
def api_points_over_time():
    try:
        days = max(7, min(180, int(request.args.get("days", 30))))
    except (ValueError, TypeError):
        days = 30
    data = load_data()
    today = datetime.now(timezone.utc).date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    index = {d: i for i, d in enumerate(labels)}
    series = {cat: [0.0] * days for cat in ALL_CATEGORIES}

    for uid, rec in user_records(data):
        for cat in ALL_CATEGORIES:
            for e in rec.get(cat, {}).get("log", []):
                day = str(e.get("time", ""))[:10]
                if day in index:
                    series[cat][index[day]] += float(e.get("points", 0) or 0)

    return jsonify({
        "labels": labels,
        "series": {cat: [round(v, 1) for v in vals] for cat, vals in series.items()},
        "totals": {cat: round(sum(vals), 1) for cat, vals in series.items()},
    })

# ── API: Role resync ──

@app.route("/api/roles/resync", methods=["POST"])
@admin_required
def api_roles_resync():
    resync = _bridge.get("resync")
    if resync is None or _bridge.get("loop") is None:
        return jsonify({"error": "Bot isn't connected yet. Try again once it's online."}), 503
    try:
        future = run_on_bot(resync())
        result = future.result(timeout=120) if future else {}
    except Exception as exc:
        return jsonify({"error": f"Resync failed: {exc}"}), 500
    return jsonify({"ok": True, **(result or {})})

# ── API: Site activity (admins only) ──

@app.route("/api/analytics")
@admin_required
def api_analytics():
    flush_visits()
    try:
        days = max(7, min(ANALYTICS_RETENTION_DAYS, int(request.args.get("days", 30))))
    except (ValueError, TypeError):
        days = 30

    data = load_data()
    analytics = data.get("_analytics", {})
    stored = analytics.get("days", {})
    last_seen = analytics.get("last_seen", {})

    today = datetime.now(timezone.utc).date()
    labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    views = []
    uniques = []
    per_user = {}
    page_totals = {}

    for day in labels:
        bucket = stored.get(day, {})
        views.append(sum(u.get("views", 0) for u in bucket.values()))
        uniques.append(len(bucket))
        for uid, entry in bucket.items():
            slot = per_user.setdefault(uid, {"views": 0, "days": 0})
            slot["views"] += entry.get("views", 0)
            slot["days"] += 1
            for page, count in (entry.get("pages") or {}).items():
                page_totals[page] = page_totals.get(page, 0) + count

    people = []
    for uid, slot in per_user.items():
        who = resolve_user(uid)
        people.append({
            "uid": uid, "name": who["name"], "avatar": who["avatar"], "resolved": who["resolved"],
            "views": slot["views"], "days": slot["days"],
            "last_seen": last_seen.get(uid, ""),
        })
    people.sort(key=lambda p: p["views"], reverse=True)

    # anyone who has signed in before but not in this window
    dormant = [uid for uid in last_seen if uid not in per_user]

    return jsonify({
        "labels": labels,
        "views": views,
        "uniques": uniques,
        "people": people[:100],
        "pages": page_totals,
        "totals": {
            "views": sum(views),
            "people": len(per_user),
            "dormant": len(dormant),
            "busiest": max(zip(views, labels))[1] if any(views) else None,
            "per_day": round(sum(views) / max(1, days), 1),
        },
    })


# ── API: Points and ranks ──

@app.route("/api/economy", methods=["GET"])
@admin_required
def api_economy_get():
    economy = get_economy()
    return jsonify({
        "events": economy["events"],
        "cooldowns": economy["cooldowns"],
        "ranks": economy["ranks"],
        "metric": _bridge["metric"] or {},
        "category_names": CATEGORY_NAMES,
        "defaults": {
            "events": default_event_points(),
            "cooldowns": default_event_cooldowns(),
            "ranks": default_ranks(),
        },
    })


@app.route("/api/economy", methods=["POST"])
@admin_required
def api_economy_save():
    body = request.json or {}
    section = body.get("section")
    category = body.get("category")
    if category not in ALL_CATEGORIES:
        return jsonify({"error": "Unknown category."}), 400

    with data_txn() as data:
        economy = data.setdefault("_economy", {})

        if section == "events":
            rows = body.get("events") or []
            cleaned = {}
            cooldowns_cleaned = {}
            for row in rows:
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                if len(name) > 60:
                    return jsonify({"error": f"'{name[:20]}...' is too long (60 characters max)."}), 400
                if name in cleaned:
                    return jsonify({"error": f"'{name}' is listed twice."}), 400
                try:
                    points = round(float(row.get("points", 0)), 2)
                except (ValueError, TypeError):
                    return jsonify({"error": f"'{name}' needs a number for points."}), 400
                if points < 0 or points > 1000:
                    return jsonify({"error": f"'{name}' must be between 0 and 1000 points."}), 400
                cleaned[name] = int(points) if points == int(points) else points

                try:
                    cooldown_minutes = float(row.get("cooldown", 0) or 0)
                except (ValueError, TypeError):
                    return jsonify({"error": f"'{name}' needs a number for cooldown."}), 400
                if cooldown_minutes < 0 or cooldown_minutes > 1440:
                    return jsonify({"error": f"'{name}' cooldown must be between 0 and 1440 minutes."}), 400
                cooldowns_cleaned[name] = int(round(cooldown_minutes * 60))
            if not cleaned:
                return jsonify({"error": "Keep at least one event in this category."}), 400

            removed = [e for e in get_economy(data)["events"].get(category, {}) if e not in cleaned]
            economy.setdefault("events", {})[category] = cleaned
            economy.setdefault("cooldowns", {})[category] = cooldowns_cleaned
            return jsonify({"ok": True, "removed": removed, "count": len(cleaned)})

        if section == "ranks":
            rows = body.get("ranks") or []
            cleaned = []
            seen_names = set()
            for row in rows:
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                if len(name) > 90:
                    return jsonify({"error": f"'{name[:20]}...' is too long for a role name."}), 400
                if name.lower() in seen_names:
                    return jsonify({"error": f"'{name}' is listed twice."}), 400
                seen_names.add(name.lower())
                try:
                    at = round(float(row.get("at", 0)), 2)
                except (ValueError, TypeError):
                    return jsonify({"error": f"'{name}' needs a number to unlock at."}), 400
                if at < 0:
                    return jsonify({"error": f"'{name}' cannot unlock below zero."}), 400
                cleaned.append([int(at) if at == int(at) else at, name])

            cleaned.sort(key=lambda r: r[0])
            for i in range(1, len(cleaned)):
                if cleaned[i][0] == cleaned[i - 1][0]:
                    return jsonify({
                        "error": f"'{cleaned[i][1]}' and '{cleaned[i-1][1]}' both unlock at {cleaned[i][0]}."
                    }), 400

            economy.setdefault("ranks", {})[category] = cleaned
            return jsonify({"ok": True, "count": len(cleaned), "ranks_changed": True})

        return jsonify({"error": "Nothing to save."}), 400


@app.route("/api/economy/reset", methods=["POST"])
@admin_required
def api_economy_reset():
    body = request.json or {}
    section = body.get("section")
    category = body.get("category")
    if category not in ALL_CATEGORIES or section not in ("events", "ranks"):
        return jsonify({"error": "Unknown category or section."}), 400
    with data_txn() as data:
        economy = data.get("_economy", {})
        if category in economy.get(section, {}):
            del economy[section][category]
        if section == "events" and category in economy.get("cooldowns", {}):
            del economy["cooldowns"][category]
    return jsonify({"ok": True})


# ── API: Custom ? commands ──

def _valid_command_name(name):
    return bool(re.fullmatch(r"[a-z0-9_-]{1,24}", name))

@app.route("/api/commands", methods=["GET"])
@admin_required
def api_commands_get():
    data = load_data()
    return jsonify(data.get("_commands", []))

@app.route("/api/commands", methods=["POST"])
@admin_required
def api_commands_save():
    body = request.json or {}
    name = str(body.get("name", "")).strip().lower().lstrip("?")
    response_text = (body.get("response") or "").strip()

    if not _valid_command_name(name):
        return jsonify({"error": "Names may use letters, numbers, - and _ only (max 24 characters)."}), 400
    if name in RESERVED_COMMANDS:
        return jsonify({"error": f"?{name} is a built-in command. Pick another name."}), 400
    if not response_text:
        return jsonify({"error": "Give the command something to say."}), 400
    if len(response_text) > 1900:
        return jsonify({"error": "Response is too long (1900 characters max)."}), 400

    with data_txn() as data:
        commands_list = data.get("_commands", [])
        entry = {
            "name": name,
            "response": response_text,
            "embed": bool(body.get("embed", False)),
            "title": (body.get("title") or "").strip()[:200],
            "color": (body.get("color") or "#7fc2b8").strip()[:7],
            "enabled": bool(body.get("enabled", True)),
            "uses": 0,
            "created_by": session.get("user", {}).get("username", "dashboard"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for i, c in enumerate(commands_list):
            if c["name"] == name:
                entry["uses"] = c.get("uses", 0)
                entry["created_at"] = c.get("created_at", entry["created_at"])
                commands_list[i] = entry
                break
        else:
            if len(commands_list) >= 100:
                return jsonify({"error": "You've hit the 100 custom command limit."}), 400
            commands_list.append(entry)

        data["_commands"] = sorted(commands_list, key=lambda c: c["name"])
    return jsonify({"ok": True, "command": entry})

@app.route("/api/commands/<name>", methods=["DELETE"])
@admin_required
def api_commands_delete(name):
    with data_txn() as data:
        commands_list = data.get("_commands", [])
        remaining = [c for c in commands_list if c["name"] != name.lower()]
        if len(remaining) == len(commands_list):
            return jsonify({"error": "No command by that name."}), 404
        data["_commands"] = remaining
    return jsonify({"ok": True})

# ── API: Event Schedule ──

@app.route("/api/events", methods=["GET"])
@admin_required
def api_events_get():
    data = load_data()
    overrides = data.get("_event_schedule", {})
    schedule = {**DEFAULT_EVENT_SCHEDULE, **overrides}
    return jsonify(schedule)

@app.route("/api/schedule", methods=["GET"])
@member_required
def api_schedule():
    """Public event ping schedule as real upcoming UTC datetimes, so the
    browser can render each one in the viewer's own local timezone instead
    of the raw Libya-time HH:MM strings admins configure."""
    data = load_data()
    overrides = data.get("_event_schedule", {})
    schedule = {**DEFAULT_EVENT_SCHEDULE, **overrides}
    now_libya = datetime.now(EVENT_SCHEDULE_TZ)
    today = now_libya.date()

    result = {}
    soonest_per_event = []
    for event, times in schedule.items():
        occurrences = []
        for t in times:
            if not isinstance(t, str) or len(t) != 5:
                continue
            try:
                hh, mm = int(t[:2]), int(t[3:5])
            except ValueError:
                continue
            occ = datetime(today.year, today.month, today.day, hh, mm, tzinfo=EVENT_SCHEDULE_TZ)
            if occ < now_libya:
                occ += timedelta(days=1)
            occurrences.append(occ)
        occurrences.sort()
        iso_list = [o.astimezone(timezone.utc).isoformat() for o in occurrences]
        result[event] = iso_list
        if iso_list:
            soonest_per_event.append({"event": event, "at": iso_list[0]})

    soonest_per_event.sort(key=lambda x: x["at"])
    return jsonify({
        "schedule": result,
        "next": soonest_per_event[0] if soonest_per_event else None,
    })

@app.route("/api/events", methods=["POST"])
@admin_required
def api_events_update():
    body = request.json or {}
    validated = {}
    for event, times in body.items():
        if isinstance(times, list):
            validated[event] = [t for t in times if isinstance(t, str) and len(t) == 5]
    with data_txn() as data:
        data["_event_schedule"] = validated
    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
# LOGIN HTML
# ─────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in - Matzys Overseer</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0c1210;--panel:#0d1614;--panel-2:#152220;--border:#233530;
  --text:#eef4f2;--muted:#8fa39d;--accent:#7fc2b8;--red:#c77a80;
  --serif:'Cinzel',ui-serif,"Iowan Old Style",Georgia,serif;
  --sans:'Space Grotesk',-apple-system,"Segoe UI",system-ui,sans-serif;
}
body{background:var(--bg);color:var(--text);font-family:var(--sans);
  min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:24px;overflow-x:hidden;position:relative}

/* Fog-lit drowned fortress backdrop - flat silhouette layers, no gradient glow */
.scene{position:fixed;inset:0;z-index:0;overflow:hidden}
.scene .sky{position:absolute;inset:0;background:linear-gradient(180deg,
    #0a1614 0%,#122420 32%,#204840 58%,#173630 76%,#0c1815 100%)}
.scene .grain{position:absolute;inset:0;opacity:.05;mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
.scene svg{position:absolute;inset:0;width:100%;height:100%}

.card{position:relative;z-index:2;background:var(--panel);border:1px solid var(--border);border-radius:4px;
  padding:40px 32px;width:100%;max-width:420px;text-align:center;box-shadow:0 30px 70px -20px rgba(0,0,0,.7)}
.mark{width:72px;height:72px;margin:0 auto 22px;border-radius:4px;display:block;object-fit:cover;
  border:1px solid var(--border)}
h1{font-family:var(--serif);font-size:26px;font-weight:600;letter-spacing:.2px}
h1 span{color:var(--accent)}
p.sub{color:var(--muted);font-size:14px;margin-top:8px;line-height:1.5}
.discord-btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;margin-top:30px;
  background:#4a52c9;color:#fff;border:1.5px solid var(--accent);border-radius:4px;padding:14px;font-size:15px;font-weight:600;
  font-family:var(--sans);cursor:pointer;text-decoration:none;box-shadow:3px 3px 0 #05100d}
.discord-btn:hover{background:#3d44a8}
.discord-btn:disabled{background:var(--panel-2);color:var(--muted);border-color:var(--border);box-shadow:none;cursor:not-allowed}
.discord-btn svg{width:22px;height:22px;fill:currentColor}
.note{margin-top:18px;font-size:12px;color:var(--muted);line-height:1.6}
.note code{font-family:ui-monospace,"SF Mono",Consolas,monospace;color:var(--text);font-size:11px}
.error{background:rgba(199,122,128,0.12);border:1px solid rgba(199,122,128,0.3);color:var(--red);
  border-radius:4px;padding:12px 14px;font-size:13px;margin-top:22px;text-align:left;line-height:1.5}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
</style>
</head>
<body>
<div class="scene" aria-hidden="true">
  <div class="sky"></div>
  <svg viewBox="0 0 1280 840" preserveAspectRatio="xMidYMid slice">
    <g fill="#284c44" opacity=".65">
      <rect x="330" y="420" width="46" height="150"/><rect x="380" y="390" width="34" height="180"/>
      <rect x="900" y="400" width="40" height="170"/><rect x="945" y="430" width="30" height="140"/>
      <polygon points="1010,570 1010,410 1050,380 1090,410 1090,570"/>
    </g>
    <g fill="#123028" opacity=".92">
      <rect x="260" y="470" width="760" height="150"/>
      <rect x="260" y="450" width="24" height="24"/><rect x="308" y="450" width="24" height="24"/>
      <rect x="356" y="450" width="24" height="24"/><rect x="404" y="450" width="24" height="24"/>
      <rect x="452" y="450" width="24" height="24"/><rect x="500" y="450" width="24" height="24"/>
      <rect x="548" y="450" width="24" height="24"/><rect x="596" y="450" width="24" height="24"/>
      <rect x="644" y="450" width="24" height="24"/><rect x="692" y="450" width="24" height="24"/>
      <rect x="740" y="450" width="24" height="24"/><rect x="788" y="450" width="24" height="24"/>
      <rect x="836" y="450" width="24" height="24"/><rect x="884" y="450" width="24" height="24"/>
      <rect x="932" y="450" width="24" height="24"/><rect x="980" y="450" width="24" height="24"/>
      <polygon points="450,470 450,340 640,270 830,340 830,470"/>
    </g>
    <g>
      <rect x="605" y="200" width="70" height="290" fill="#0a1c18"/>
      <polygon points="600,200 680,200 690,170 640,150 590,170" fill="#0a1c18"/>
      <rect x="612" y="130" width="56" height="42" fill="#0d211c"/>
      <polygon points="600,130 680,130 664,96 616,96" fill="#0d211c"/>
      <rect x="636" y="70" width="8" height="30" fill="#0d211c"/>
      <polygon points="570,220 590,220 590,300 570,340" fill="#081a16"/>
      <polygon points="710,220 690,220 690,300 710,340" fill="#081a16"/>
    </g>
    <g fill="#061511"><path d="M0,560 C220,520 1060,520 1280,565 L1280,840 L0,840 Z"/></g>
    <g fill="#04100c">
      <rect x="40" y="545" width="14" height="90"/><rect x="120" y="538" width="14" height="90"/>
      <rect x="205" y="532" width="14" height="90"/><rect x="295" y="527" width="14" height="90"/>
      <rect x="390" y="524" width="14" height="90"/><rect x="490" y="522" width="14" height="95"/>
      <rect x="600" y="522" width="14" height="95"/><rect x="700" y="523" width="14" height="90"/>
      <rect x="800" y="525" width="14" height="90"/><rect x="900" y="529" width="14" height="90"/>
      <rect x="1000" y="534" width="14" height="90"/><rect x="1100" y="541" width="14" height="90"/>
      <rect x="1190" y="549" width="14" height="90"/>
    </g>
    <g fill="#04100c">
      <rect x="20" y="533" width="30" height="24"/><rect x="90" y="524" width="30" height="24"/>
      <rect x="165" y="518" width="30" height="24"/><rect x="250" y="512" width="30" height="24"/>
      <rect x="340" y="509" width="30" height="24"/><rect x="440" y="507" width="30" height="24"/>
      <rect x="545" y="507" width="30" height="24"/><rect x="650" y="507" width="30" height="24"/>
      <rect x="755" y="508" width="30" height="24"/><rect x="855" y="511" width="30" height="24"/>
      <rect x="955" y="515" width="30" height="24"/><rect x="1055" y="521" width="30" height="24"/>
      <rect x="1155" y="529" width="30" height="24"/><rect x="1240" y="537" width="30" height="24"/>
    </g>
    <g fill="#030d0a">
      <polygon points="120,700 160,660 200,700"/><polygon points="210,712 250,668 290,712"/>
      <polygon points="760,706 800,664 840,706"/><polygon points="900,714 935,672 970,714"/>
      <polygon points="1010,704 1050,660 1090,704"/>
    </g>
    <g filter="url(#loginGlow)">
      <circle cx="470" cy="150" r="9" fill="#eafff9"/><circle cx="493" cy="135" r="6" fill="#eafff9"/>
      <circle cx="900" cy="120" r="10" fill="#eafff9"/><circle cx="925" cy="105" r="7" fill="#eafff9"/>
      <circle cx="770" cy="220" r="5" fill="#d6fff5" opacity=".7"/><circle cx="350" cy="240" r="4" fill="#d6fff5" opacity=".65"/>
    </g>
    <defs><filter id="loginGlow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="3.2"/></filter></defs>
  </svg>
  <div class="grain"></div>
</div>

<div class="card">
  <img class="mark" src="__LOGO__" alt="">
  <h1>Matzys <span>Overseer</span></h1>

  {% if error %}<div class="error">{{ error }}</div>{% endif %}

  {% if configured %}
  <a class="discord-btn" href="/login/discord">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.3 4.4A19.8 19.8 0 0 0 15.4 3l-.24.5c1.6.38 2.9 1 4.1 1.9a13.9 13.9 0 0 0-4.9-1.5 17.4 17.4 0 0 0-4.7 0c-.5.06-1.2.2-2.1.4-.9.2-1.6.5-2.1.7 1.2-.9 2.5-1.5 4-1.9L9.2 3a19.8 19.8 0 0 0-4.9 1.4C2.7 6.9 1.8 9.8 1.6 13a15 15 0 0 0 4.5 2.3c.4-.5.7-1 1-1.6-.6-.2-1.1-.5-1.5-.8l.4-.3a11.9 11.9 0 0 0 10.2 0l.4.3c-.5.3-1 .6-1.6.8.3.6.6 1.1 1 1.6a15 15 0 0 0 4.5-2.3c-.2-3.6-1.3-6.5-3.2-8.6ZM8.6 12.7c-.9 0-1.6-.9-1.6-1.9s.7-1.9 1.6-1.9 1.7.8 1.6 1.9c0 1-.7 1.9-1.6 1.9Zm6 0c-.9 0-1.6-.9-1.6-1.9s.7-1.9 1.6-1.9 1.7.8 1.6 1.9c0 1-.7 1.9-1.6 1.9Z"/></svg>
    Continue with Discord
  </a>
  {% else %}
  <button class="discord-btn" disabled>Discord login not configured</button>
  <div class="note">Set <code>DISCORD_CLIENT_ID</code>, <code>DISCORD_CLIENT_SECRET</code> and
    <code>DISCORD_REDIRECT_URI</code> in your Railway variables, then reload this page.</div>
  {% endif %}
</div>
</body>
</html>""".replace("__LOGO__", LOGO_SRC)


# ─────────────────────────────────────────────────────────────
# PUBLIC SITE (any signed-in member) - Announcements, Leaderboards,
# Live now, Event schedule, Server pulse, Members, Profile
# ─────────────────────────────────────────────────────────────

PUBLIC_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Matzys Overseer</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap">
<style>
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
:root{
  --bg:#0c1210;--header:#0d1614;--card:#0d1614;--card-2:#152220;--border:#233530;--border-2:#324b44;
  --accent:#7fc2b8;--accent-dim:#1f3d37;--moon:#7fc2b8;--steel:#9c8fe0;--sage:#5fcf9f;--red:#c77a80;--amber:#d1a86a;
  --text:#eef4f2;--muted:#8fa39d;--dim:#5c6f69;
  --serif:'Cinzel',ui-serif,"Iowan Old Style",Georgia,serif;
  --sans:'Space Grotesk',-apple-system,"Segoe UI",system-ui,sans-serif;
  --mono:ui-monospace,"SF Mono",Consolas,monospace;
  --radius:4px;
}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100dvh;-webkit-font-smoothing:antialiased}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
img,svg{display:block}
button{font:inherit;cursor:pointer}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}

/* ── Shell ── */
.app{display:flex;min-height:100dvh}
.sidebar{width:246px;flex-shrink:0;background:var(--header);border-right:1px solid var(--border);
  display:flex;flex-direction:column;padding:20px 0;position:sticky;top:0;height:100dvh}
.sb-head{display:flex;align-items:center;gap:11px;padding:0 20px 18px;border-bottom:1px solid var(--border);margin-bottom:10px}
.sb-mark{width:34px;height:34px;border-radius:10px;display:block;object-fit:cover;flex-shrink:0;border:1px solid var(--border)}
.sb-head h2{font-family:var(--serif);font-size:15px;font-weight:500}
.sb-head p{font-size:10.5px;color:var(--dim);margin-top:1px}
.sb-group{padding:0 12px;flex:1;overflow-y:auto}
.sb-label{font-size:10px;letter-spacing:1.3px;text-transform:uppercase;color:var(--dim);padding:12px 10px 5px}
.sb-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:10px;cursor:pointer;
  color:var(--muted);font-size:13.5px;font-weight:500;transition:all .15s;margin-bottom:1px;
  text-decoration:none;background:none;border:none;width:100%;text-align:left;font-family:inherit}
.sb-item:hover{color:var(--text);background:var(--card-2)}
.sb-item.active{color:var(--accent);background:rgba(127,194,184,.12)}
.sb-item svg{width:16px;height:16px;flex-shrink:0;stroke:currentColor;fill:none;stroke-width:1.8}
.sb-item .live-dot{width:6px;height:6px;border-radius:50%;background:var(--sage);margin-left:auto;flex-shrink:0;display:none}
.sb-item .live-dot.on{display:block}
.sb-foot{padding:12px 20px 0;margin-top:8px;border-top:1px solid var(--border)}
.sb-user{display:flex;align-items:center;gap:10px}
.sb-user img{width:30px;height:30px;border-radius:50%;flex-shrink:0;border:1px solid var(--border)}
.sb-user .nm{font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:130px}
.sb-user .rl{font-size:10px;color:var(--dim)}
.sb-signout{color:var(--dim);text-decoration:none;font-size:11px;margin-left:auto;flex-shrink:0}
.sb-signout:hover{color:var(--muted)}

.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{display:flex;align-items:center;gap:14px;padding:16px 32px;border-bottom:1px solid var(--border)}
.topbar .crumb{font-size:12.5px;color:var(--dim)}
.topbar .crumb b{color:var(--muted);font-weight:500}
.topbar .spacer{flex:1}

.hamburger{display:none;background:none;border:none;color:var(--text);cursor:pointer;padding:6px;border-radius:8px;flex-shrink:0}
.hamburger:hover{background:var(--card-2)}
.hamburger svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round}
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:85;opacity:0;pointer-events:none;transition:opacity .2s}
.overlay.show{opacity:1;pointer-events:auto}
@media (max-width:900px){
  .hamburger{display:flex;align-items:center;justify-content:center}
  .overlay{display:block}
  .sidebar{position:fixed;top:0;left:0;height:100dvh;z-index:90;transform:translateX(-100%);transition:transform .22s ease}
  .sidebar.open{transform:none}
}

.tabpane{display:none;padding:30px 34px 44px;max-width:960px}
.tabpane.active{display:block;animation:fade .2s ease}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.p-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.p-head h1{font-family:var(--serif);font-size:22px;font-weight:500}
.p-head .sub{font-size:13px;color:var(--muted);margin-top:4px}

.hero{position:relative;padding-bottom:6px}
.hero::before{content:'';position:absolute;top:-20px;right:-6%;width:300px;height:300px;border-radius:50%;
  background:radial-gradient(circle,rgba(127,194,184,.14),rgba(127,194,184,.02) 55%,transparent 72%);pointer-events:none;z-index:-1}
.hero h1{font-family:var(--serif);font-size:clamp(24px,3.6vw,32px);font-weight:500}
.hero p{margin-top:8px;font-size:14px;color:var(--muted)}

.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:22px;margin-bottom:14px}
.card h3{font-family:var(--serif);font-size:15.5px;font-weight:500;margin-bottom:4px}
.card .hint{font-size:12.5px;color:var(--muted);margin-bottom:16px}

.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px 18px}
.stat .lbl{font-size:11.5px;color:var(--muted)}
.stat .val{font-family:var(--serif);font-size:22px;margin-top:6px}
.stat .delta{font-size:11.5px;margin-top:6px;font-family:var(--mono)}
.up{color:var(--sage)}.down{color:var(--red)}.flat{color:var(--dim)}

.tabs{display:flex;gap:3px;background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:4px;width:fit-content;max-width:100%;overflow-x:auto;margin-bottom:16px}
.tab{padding:7px 15px;border-radius:9px;cursor:pointer;font-size:13px;font-weight:500;color:var(--muted);
  white-space:nowrap;border:none;background:none;font-family:inherit}
.tab.active{background:var(--card-2);color:var(--text)}
.controls{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.controls select,.controls input{background:var(--card-2);border:1px solid var(--border);border-radius:10px;
  padding:9px 12px;color:var(--text);font-size:13px;font-family:var(--sans);outline:none}
.controls input{min-width:170px}
.controls select:focus,.controls input:focus{border-color:var(--accent)}

.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px 12px;color:var(--dim);font-weight:500;font-size:10px;text-transform:uppercase;
  letter-spacing:.7px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:11px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--card-2)}
tr.me td{background:rgba(127,194,184,.07)}
.mono{font-family:var(--mono);color:var(--muted)}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right}
.pos{font-family:var(--mono);color:var(--dim);width:26px}
.who{display:flex;align-items:center;gap:9px;text-decoration:none;color:var(--text)}
.who img,.who .ph{width:28px;height:28px;border-radius:50%;flex-shrink:0;background:var(--card-2);border:1px solid var(--border)}
.who .ph{display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--muted);font-weight:600}
.tag{font-size:10px;color:var(--bg);background:var(--accent);border-radius:5px;padding:2px 6px;margin-left:7px;font-weight:600}

.row-link{display:flex;align-items:center;gap:13px;padding:12px 14px;border-radius:12px;text-decoration:none;
  color:var(--text);background:var(--card);border:1px solid var(--border);margin-bottom:7px;transition:border-color .15s}
.row-link:hover{border-color:var(--border-2)}
.row-link.me{border-color:var(--accent)}
.row-link .who{flex:1;min-width:0}
.row-link .nm{font-size:14px;font-weight:500}
.row-link .rk{font-size:11.5px;color:var(--muted);margin-top:2px}
.row-link .pts{text-align:right;flex-shrink:0}
.row-link .pts b{display:block;font-family:var(--mono);font-size:14.5px;font-weight:600}
.row-link .pts span{font-size:10.5px;color:var(--dim)}

.pill{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;padding:3px 9px;border-radius:99px;font-weight:500}
.pill.host{background:rgba(127,194,184,.14);color:var(--accent)}
.pill.security{background:rgba(156,143,224,.14);color:var(--steel)}
.pill.support{background:rgba(95,207,159,.14);color:var(--sage)}

.stage-card{background:linear-gradient(155deg,var(--card-2),var(--card));border:1px solid var(--border-2);
  border-radius:18px;padding:26px;margin-bottom:16px;position:relative;overflow:hidden}
.stage-card::after{content:'';position:absolute;top:-40%;right:-15%;width:220px;height:220px;border-radius:50%;
  background:radial-gradient(circle,rgba(127,194,184,.16),transparent 70%)}
.stage-badge{display:inline-flex;align-items:center;gap:6px;background:var(--sage);color:#0d1710;
  font-size:11px;font-weight:700;padding:4px 10px;border-radius:7px;letter-spacing:.3px;position:relative}
.stage-badge i{width:6px;height:6px;border-radius:50%;background:#0d1710}
.stage-name{font-family:var(--serif);font-size:22px;margin-top:14px;position:relative}
.stage-meta{font-size:13px;color:var(--muted);margin-top:8px;position:relative}
.stage-meta b{color:var(--text);font-weight:500}

.post{border-bottom:1px solid var(--border);padding:18px 0}
.post:first-child{padding-top:0}
.post:last-child{border-bottom:none;padding-bottom:0}
.post-meta{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--dim);margin-bottom:8px}
.post-meta b{color:var(--accent);font-weight:600}
.post-text{font-size:14px;line-height:1.6;white-space:pre-wrap}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:640px){.grid-2{grid-template-columns:1fr}}
.evt-card h3{font-size:14.5px;margin-bottom:8px}
.evt-time{font-family:var(--mono);color:var(--accent);font-size:12.5px}
.evt-role{font-size:11.5px;color:var(--muted);margin-top:4px}

.next-ping{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.next-ping .big{font-family:var(--serif);font-size:20px}
.next-ping .when{font-family:var(--mono);color:var(--accent);font-size:13px}

.rank-card{background:var(--card-2);border-radius:12px;padding:14px}
.rank-top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:9px;flex-wrap:wrap}
.rank-name{font-size:14px;font-weight:600}
.rank-next{font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.rank-bar{height:7px;border-radius:4px;background:var(--border);overflow:hidden}
.rank-fill{height:100%;border-radius:4px;transition:width .5s ease}
.cat-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.cat-name{font-size:16px;font-weight:600}
.cat-pos{font-size:12px;color:var(--muted);font-family:var(--mono)}
.cat-stats{display:flex;gap:22px;margin-top:16px;flex-wrap:wrap}
.cat-stats div{font-size:12.5px;color:var(--muted)}
.cat-stats b{display:block;font-family:var(--mono);font-size:18px;color:var(--text);font-weight:600;margin-bottom:2px}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}
.chip{background:var(--card-2);border:1px solid var(--border);border-radius:8px;padding:5px 11px;font-size:12px;color:var(--muted)}
.chip b{color:var(--text);font-family:var(--mono)}
.top-badge{width:20px;height:20px;border-radius:5px;image-rendering:pixelated;flex-shrink:0;
  border:1px solid rgba(0,0,0,.35);box-shadow:0 1px 2px rgba(0,0,0,.35);vertical-align:middle}
.top-badge-lg{width:40px;height:40px;border-radius:8px}
.rivals{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.rival{background:var(--card-2);border:1px solid var(--border);border-radius:9px;padding:7px 11px;
  font-size:12px;color:var(--muted);text-decoration:none;display:inline-block}
a.rival:hover{border-color:var(--border-2);color:var(--text)}
.rival b{color:var(--text)}
.goals{margin-top:16px;border-top:1px solid var(--border);padding-top:14px}
.goal{margin-bottom:12px}
.goal:last-child{margin-bottom:0}
.goal .g-top{font-size:13px;margin-bottom:6px}
.goal .g-top b{font-weight:600}
.routes{display:flex;flex-wrap:wrap;gap:6px}
.route{background:var(--card-2);border:1px solid var(--border);border-radius:8px;padding:4px 9px;
  font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.route b{color:var(--text)}

.streak-top{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}
.streak-num{font-family:var(--serif);font-size:32px;font-weight:500;line-height:1}
.streak-word{font-size:13px;color:var(--muted)}
.streak-best{margin-left:auto;font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.streak-msg{font-size:13px;color:var(--muted);line-height:1.5}
.streak-msg.warn{color:var(--amber)}
.bests{display:flex;flex-wrap:wrap;gap:18px}
.bests div{font-size:12px;color:var(--muted)}
.bests b{display:block;font-family:var(--mono);font-size:15px;color:var(--text);font-weight:600;margin-bottom:2px}

.toggle-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}
.toggle-row:last-child{border-bottom:none}
.toggle-row .t-label{font-size:13.5px;font-weight:500}
.toggle-row .t-sub{font-size:12px;color:var(--muted);margin-top:2px}
.toggle{position:relative;width:42px;height:24px;flex-shrink:0}
.toggle input{opacity:0;width:0;height:0;position:absolute}
.tslider{position:absolute;inset:0;background:var(--border-2);border-radius:24px;transition:.2s;cursor:pointer}
.toggle input:checked + .tslider{background:var(--accent)}
.tslider:before{content:'';position:absolute;width:18px;height:18px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
.toggle input:checked + .tslider:before{transform:translateX(18px)}

.btn{padding:9px 16px;border-radius:10px;border:none;cursor:pointer;font-size:13px;font-weight:500;
  font-family:var(--sans);transition:background .15s}
.btn-primary{background:var(--accent);color:#1a1118}
.btn-primary:hover{background:#d59fb6}
.btn-soft{background:var(--card-2);color:var(--text);border:1px solid var(--border)}
.btn-soft:hover{background:var(--border)}

.chart-wrap{width:100%;overflow:hidden}
.chart-wrap svg{width:100%;height:auto;display:block}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:12px;color:var(--muted)}
.legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:6px}

.empty{text-align:center;padding:40px 20px;color:var(--dim);font-size:13.5px;line-height:1.6}
.empty-card{background:var(--card);border:1px dashed var(--border-2);border-radius:16px;padding:48px 24px;text-align:center}
.empty-card .ic{width:34px;height:34px;margin:0 auto 14px;color:var(--dim)}
.empty-card .ic svg{width:100%;height:100%;stroke:currentColor;fill:none;stroke-width:1.4}
.empty-card h4{font-family:var(--serif);font-size:15px;font-weight:500;margin-bottom:5px}
.empty-card p{font-size:12.5px;color:var(--muted);max-width:34ch;margin:0 auto}
</style>
</head>
<body>
<div class="overlay" id="overlay" onclick="closeDrawer()"></div>
<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="sb-head">
      <img class="sb-mark" src="__LOGO__" alt="">
      <div><h2>Matzys Overseer</h2><p>Kyrsgarde</p></div>
    </div>
    <nav class="sb-group">
      <button class="sb-item" data-tab="announcements" onclick="showTab('announcements',this)">
        <svg viewBox="0 0 24 24"><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>Announcements</button>
      <button class="sb-item" data-tab="leaderboards" onclick="showTab('leaderboards',this)">
        <svg viewBox="0 0 24 24"><path d="M5 21V11M12 21V4M19 21v-6"/></svg>Leaderboards</button>
      <button class="sb-item" data-tab="live" onclick="showTab('live',this)">
        <svg viewBox="0 0 24 24"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 3v18M3 12h18"/></svg>Live now<span class="live-dot" id="live-dot"></span></button>
      <button class="sb-item" data-tab="schedule" onclick="showTab('schedule',this)">
        <svg viewBox="0 0 24 24"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2"/></svg>Event schedule</button>
      <button class="sb-item" data-tab="pulse" onclick="showTab('pulse',this)">
        <svg viewBox="0 0 24 24"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>Server pulse</button>
      <button class="sb-item" data-tab="members" onclick="showTab('members',this)">
        <svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>Members</button>
      <button class="sb-item" data-tab="profile" onclick="showTab('profile',this)">
        <svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8"/></svg>My profile</button>
      {% if is_admin %}
      <div class="sb-label">Admin</div>
      <a class="sb-item" href="/dashboard">
        <svg viewBox="0 0 24 24"><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3M13 4.5v5M7 9.5v5M13 14.5v5"/></svg>Admin dashboard</a>
      {% if user.id == 1387930623766827140 %}
      <a class="sb-item" href="/dashboard/admin/ips">
        <svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10A10 10 0 0 1 2 12 10 10 0 0 1 12 2M12 4a8 8 0 0 0-8 8 8 8 0 0 0 8 8 8 8 0 0 0 8-8 8 8 0 0 0-8-8M13 8h-2v4h-4v2h4v4h2v-4h4v-2h-4z"/></svg>IP Management</a>
      {% endif %}
      {% endif %}
    </nav>
    <div class="sb-foot">
      <div class="sb-user">
        <img id="sb-avatar" src="{{ user.avatar }}" alt="">
        <div><div class="nm">{{ user.username }}</div><div class="rl">{% if is_admin %}Administrator{% else %}Member{% endif %}</div></div>
        <a class="sb-signout" href="/logout">Sign out</a>
      </div>
      <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:11px;">
        <a href="/terms" style="display:block;color:var(--muted);text-decoration:none;margin-bottom:6px">Terms of Service</a>
        <a href="/privacy" style="display:block;color:var(--muted);text-decoration:none;margin-bottom:6px">Privacy Policy</a>
        <button onclick="verifyIP()" style="width:100%;padding:6px;background:#152220;border:1px solid #233530;color:#7fc2b8;border-radius:4px;cursor:pointer;font-size:11px;margin-top:6px">Verify Access</button>
      </div>
    </div>
  </aside>

  <div class="main">
    <div class="topbar">
      <button class="hamburger" onclick="openDrawer()" aria-label="Open menu">
        <svg viewBox="0 0 24 24"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
      </button>
      <span class="crumb"><b>Kyrsgarde</b> / <span id="crumb-name">Announcements</span></span>
      <div class="spacer"></div>
    </div>

    <!-- ANNOUNCEMENTS -->
    <div class="tabpane" id="pane-announcements">
      <div class="hero"><h1>Announcements</h1><p>What's new with the bot.</p></div>
      <div class="card" style="margin-top:22px"><div id="announcements-list"><div class="empty">Loading…</div></div></div>
    </div>

    <!-- LEADERBOARDS -->
    <div class="tabpane" id="pane-leaderboards">
      <div class="p-head"><h1>Leaderboards</h1></div>
      <div class="tabs" id="lb-tabs">
        <button class="tab active" data-cat="pve" onclick="switchLbTab('pve',this)">Host</button>
        <button class="tab" data-cat="security" onclick="switchLbTab('security',this)">Security</button>
        <button class="tab" data-cat="support" onclick="switchLbTab('support',this)">Support</button>
        <button class="tab" data-cat="givers" onclick="switchLbTab('givers',this)">Vouchers</button>
      </div>
      <div class="controls" id="lb-giver-range" style="display:none">
        <select id="lb-days" onchange="loadGiverBoard()">
          <option value="0">All time</option><option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option><option value="90">Last 90 days</option>
        </select>
      </div>
      <div class="card"><div class="table-wrap" id="lb-table"><div class="empty">Loading…</div></div></div>
    </div>

    <!-- LIVE NOW -->
    <div class="tabpane" id="pane-live">
      <div class="p-head"><h1>Live now</h1></div>
      <div id="live-content"><div class="empty">Loading…</div></div>
    </div>

    <!-- EVENT SCHEDULE -->
    <div class="tabpane" id="pane-schedule">
      <div class="p-head"><h1>Event schedule</h1><div class="sub" style="width:100%">Shown in your local time.</div></div>
      <div id="schedule-content"><div class="empty">Loading…</div></div>
    </div>

    <!-- SERVER PULSE -->
    <div class="tabpane" id="pane-pulse">
      <div class="p-head"><h1>Server pulse</h1><div class="sub" style="width:100%">A snapshot of the last 7 days.</div></div>
      <div id="pulse-content"><div class="empty">Loading…</div></div>
    </div>

    <!-- MEMBERS -->
    <div class="tabpane" id="pane-members">
      <div class="p-head"><h1>Members</h1></div>
      <div class="controls">
        <input id="m-q" placeholder="Search by name">
      </div>
      <div class="tabs" id="m-tabs">
        <button class="tab active" data-sort="total" onclick="switchMemberSort('total',this)">Total</button>
        <button class="tab" data-sort="pve" onclick="switchMemberSort('pve',this)">Host</button>
        <button class="tab" data-sort="security" onclick="switchMemberSort('security',this)">Security</button>
        <button class="tab" data-sort="support" onclick="switchMemberSort('support',this)">Support</button>
      </div>
      <div id="members-sub" class="hint" style="margin-bottom:12px"></div>
      <div id="members-list"><div class="empty">Loading…</div></div>
    </div>

    <!-- PROFILE -->
    <div class="tabpane" id="pane-profile">
      <div class="hero" id="profile-hero">
        <h1>Welcome back, <span id="profile-hero-name"></span><span id="profile-hero-badge"></span></h1>
        <p id="profile-hero-sub">Here is where you stand.</p>
      </div>
      <div class="stat-grid" style="margin-top:18px">
        <div class="stat"><div class="val" id="s-total">-</div><div class="lbl">Total points</div></div>
        <div class="stat"><div class="val" id="s-week">-</div><div class="lbl">Points this week</div><div class="delta" id="s-delta"></div></div>
        <div class="stat"><div class="val" id="s-vouches">-</div><div class="lbl">Total vouches</div></div>
      </div>
      <div class="card" id="streak-card"></div>
      <div class="card"><div class="bests" id="bests"></div></div>
      <div id="cats"></div>
      <h2 style="font-family:var(--serif);font-size:18px;font-weight:500;margin:22px 0 12px" id="activity-heading">Your activity</h2>
      <div class="card">
        <div class="chart-wrap" id="chart"><div class="empty">Loading…</div></div>
        <div class="legend" id="chart-legend"></div>
      </div>
      <div id="profile-own-only">
        <h2 style="font-family:var(--serif);font-size:18px;font-weight:500;margin:22px 0 12px">Notification preferences</h2>
        <div class="card">
          <div class="toggle-row">
            <div><div class="t-label">Host streak reminders</div><div class="t-sub">DM when your 24h streak is about to expire</div></div>
            <label class="toggle"><input type="checkbox" id="pref-streak" onchange="savePrefs()"><span class="tslider"></span></label>
          </div>
          <div class="toggle-row">
            <div><div class="t-label">Rank up congratulations</div><div class="t-sub">DM when you climb to a new rank role</div></div>
            <label class="toggle"><input type="checkbox" id="pref-rankup" onchange="savePrefs()"><span class="tslider"></span></label>
          </div>
        </div>
        <h2 style="font-family:var(--serif);font-size:18px;font-weight:500;margin:22px 0 12px">Your vouch history</h2>
        <div class="card">
          <div class="controls">
            <select id="f-cat"><option value="">All categories</option>
              <option value="pve">Host</option><option value="security">Security</option><option value="support">Support</option></select>
            <select id="f-days"><option value="0">All time</option><option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option><option value="90">Last 90 days</option></select>
            <input id="f-q" placeholder="Search event or staff">
            <button class="btn btn-soft" id="f-export">Export CSV</button>
          </div>
          <div class="hint mono" id="hist-sum"></div>
          <div class="table-wrap" id="history"><div class="empty">Loading…</div></div>
        </div>
      </div>
    </div>

  </div>
</div>

<script>
const CAT_NAMES = {pve:'Host', security:'Security', support:'Support'};
const CAT_COLORS = {pve:'#7fc2b8', security:'#9c8fe0', support:'#5fcf9f'};
const IS_ADMIN = {{ 'true' if is_admin else 'false' }};
const VIEWING = "{{ viewing_uid|default('', true) }}";
const VIEWING_NAME = "{{ viewing_name|default('', true) }}";
const INITIAL_TAB = "{{ initial_tab|default('announcements', true) }}";

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function fmt(n){return typeof n==='number'?n.toLocaleString('en-US',{maximumFractionDigits:1}):n;}
function timeAgo(iso){
  if(!iso) return '';
  const then = new Date(iso);
  if(isNaN(then)) return '';
  const mins = Math.floor((Date.now() - then.getTime()) / 60000);
  if(mins < 1) return 'just now';
  if(mins < 60) return mins + 'm ago';
  const hours = Math.floor(mins / 60);
  if(hours < 24) return hours + 'h ago';
  return Math.floor(hours / 24) + 'd ago';
}
function localTime(iso){
  const d = new Date(iso);
  return isNaN(d) ? '-' : d.toLocaleTimeString(undefined, {hour:'numeric', minute:'2-digit'});
}
async function api(path, opts){
  const r = await fetch(path, opts);
  if(r.status === 401){ window.location.href = '/login'; throw new Error('unauthorized'); }
  return r.json();
}

/* ── Tab switching ── */
const loaded = {};
function showTab(tab, el){
  document.querySelectorAll('.sb-item[data-tab]').forEach(function(i){ i.classList.remove('active'); });
  document.querySelectorAll('.tabpane').forEach(function(p){ p.classList.remove('active'); });
  if(el) el.classList.add('active');
  else { const item = document.querySelector('.sb-item[data-tab="'+tab+'"]'); if(item) item.classList.add('active'); }
  const pane = document.getElementById('pane-' + tab);
  if(!pane) return;
  pane.classList.add('active');
  const names = {announcements:'Announcements', leaderboards:'Leaderboards', live:'Live now',
    schedule:'Event schedule', pulse:'Server pulse', members:'Members', profile:'My profile'};
  document.getElementById('crumb-name').textContent = names[tab] || tab;
  const url = new URL(window.location);
  url.searchParams.set('tab', tab);
  if(tab !== 'profile') url.searchParams.delete('uid');
  history.replaceState(null, '', url);
  closeDrawer();
  if(!loaded[tab]){
    loaded[tab] = true;
    ({announcements: loadAnnouncements, leaderboards: loadLeaderboard, live: loadLive,
      schedule: loadSchedule, pulse: loadPulse, members: loadMembers, profile: loadProfile}[tab] || function(){})();
  }
}
function openDrawer(){ document.getElementById('sidebar').classList.add('open'); document.getElementById('overlay').classList.add('show'); }
function closeDrawer(){ document.getElementById('sidebar').classList.remove('open'); document.getElementById('overlay').classList.remove('show'); }

async function verifyIP(){
  try {
    const res = await fetch('/verify', {method: 'POST'});
    if(res.status === 403){ alert('🚫 Your IP is banned. Contact an administrator.'); return; }
    if(!res.ok){ alert('⚠️ Verification failed'); return; }
    const data = await res.json();
    if(data.verified){ alert('✅ Access verified! Your IP has been logged and you have the event access role.'); }
  } catch(e){ alert('❌ Error: ' + e.message); }
}

/* ── Announcements ── */
async function loadAnnouncements(){
  const el = document.getElementById('announcements-list');
  let d;
  try { d = await api('/api/announcements'); } catch(e){ return; }
  if(!d.length){ el.innerHTML = '<div class="empty">No announcements yet.</div>'; return; }
  el.innerHTML = d.map(function(u){
    return '<div class="post"><div class="post-meta"><b>Bot Update</b> · Posted by ' + esc(u.posted_by || 'staff') +
      ' · ' + timeAgo(u.posted_at) + (u.edited_at ? ' · edited' : '') + '</div>' +
      '<div class="post-text">' + esc(u.content) + '</div></div>';
  }).join('');
}

/* ── Leaderboards ── */
let lbData = {};
let currentLbCat = 'pve';
async function loadLeaderboard(){
  if(!Object.keys(lbData).length) lbData = await api('/api/leaderboard');
  renderLbTable(currentLbCat);
}
function switchLbTab(cat, el){
  currentLbCat = cat;
  document.querySelectorAll('#lb-tabs .tab').forEach(function(t){ t.classList.remove('active'); });
  el.classList.add('active');
  const isGivers = cat === 'givers';
  document.getElementById('lb-giver-range').style.display = isGivers ? 'flex' : 'none';
  if(isGivers) loadGiverBoard(); else renderLbTable(cat);
}
function memberCell(m){
  const pic = m.avatar ? '<img alt="" src="' + m.avatar + '">' : '<span class="ph">' + esc((m.name||'?').slice(0,1).toUpperCase()) + '</span>';
  return '<a class="who" href="?tab=profile&uid=' + encodeURIComponent(m.uid) + '" onclick="return gotoProfile(\\''+m.uid+'\\', event)">' + pic + esc(m.name) + '</a>';
}
function renderLbTable(cat){
  const rows = lbData[cat] || [];
  const wrap = document.getElementById('lb-table');
  if(!rows.length){ wrap.innerHTML = '<div class="empty">No vouches recorded yet.</div>'; return; }
  wrap.innerHTML = '<table><thead><tr><th></th><th>Member</th><th style="text-align:right">Points</th><th style="text-align:right">Vouches</th></tr></thead><tbody>' +
    rows.map(function(r,i){ return '<tr' + (r.uid===MY_ID?' class="me"':'') + '><td class="pos">' + (i+1) + '</td><td>' + memberCell(r) +
      '</td><td class="num">' + fmt(r.points) + '</td><td class="num" style="color:var(--muted)">' + r.vouches + '</td></tr>'; }).join('') +
    '</tbody></table>';
}
async function loadGiverBoard(){
  const wrap = document.getElementById('lb-table');
  wrap.innerHTML = '<div class="empty">Loading…</div>';
  const days = document.getElementById('lb-days').value;
  const d = await api('/api/givers?days=' + days);
  if(!d.givers || !d.givers.length){ wrap.innerHTML = '<div class="empty">No Host vouches given in this window.</div>'; return; }
  wrap.innerHTML = '<table><thead><tr><th></th><th>Voucher</th><th style="text-align:right">Given</th><th style="text-align:right">Hosters</th><th style="text-align:right">Points</th></tr></thead><tbody>' +
    d.givers.map(function(g,i){
      const who = g.uid ? memberCell(g) : '<span>' + esc(g.name) + '</span>';
      return '<tr><td class="pos">' + (i+1) + '</td><td>' + who + '</td><td class="num">' + fmt(g.given) +
        '</td><td class="num" style="color:var(--muted)">' + g.people + '</td><td class="num">' + fmt(g.points) + '</td></tr>';
    }).join('') + '</tbody></table>';
}

/* ── Live now ── */
async function loadLive(){
  const el = document.getElementById('live-content');
  let d;
  try { d = await api('/api/live_now'); } catch(e){ return; }
  document.getElementById('live-dot').classList.toggle('on', d.length > 0);
  if(!d.length){
    el.innerHTML = '<div class="empty-card"><div class="ic"><svg viewBox="0 0 24 24" stroke="currentColor" fill="none" stroke-width="1.4"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2"/></svg></div>' +
      '<h4>Nothing live right now</h4><p>Check Event schedule for the next world event ping.</p></div>';
    return;
  }
  el.innerHTML = d.map(function(s){
    const mins = s.started_at ? Math.max(0, Math.floor((Date.now() - new Date(s.started_at).getTime()) / 60000)) : null;
    const running = mins === null ? '' : (' · running for ' + (mins < 60 ? mins + 'm' : Math.floor(mins/60) + 'h ' + (mins%60) + 'm'));
    const co = s.co_hosts && s.co_hosts.length ? ', co-host ' + s.co_hosts.map(esc).join(', ') : '';
    return '<div class="stage-card"><span class="stage-badge"><i></i>LIVE</span>' +
      '<div class="stage-name">' + esc(s.event) + '</div>' +
      '<div class="stage-meta">' + esc(s.stage || 'a stage') + ' · hosted by <b>' + esc(s.host) + '</b>' + co + running + '</div></div>';
  }).join('');
}

/* ── Event schedule ── */
async function loadSchedule(){
  const el = document.getElementById('schedule-content');
  let d;
  try { d = await api('/api/schedule'); } catch(e){ return; }
  let html = '';
  if(d.next){
    html += '<div class="card"><div class="next-ping"><span>Next up:</span><span class="big">' + esc(d.next.event) +
      '</span><span class="when">' + localTime(d.next.at) + '</span></div></div>';
  }
  html += '<div class="grid-2">' + Object.entries(d.schedule).map(function(kv){
    const event = kv[0], times = kv[1];
    const chips = times.slice(0, 8).map(function(t){ return '<span class="chip">' + localTime(t) + '</span>'; }).join('');
    return '<div class="card evt-card" style="margin-bottom:0"><h3>' + esc(event) + '</h3>' +
      '<div class="chips" style="margin-top:0">' + chips + '</div></div>';
  }).join('') + '</div>';
  el.innerHTML = html;
}

/* ── Server pulse ── */
async function loadPulse(){
  const el = document.getElementById('pulse-content');
  let d;
  try { d = await api('/api/pulse'); } catch(e){ return; }
  const topHost = d.top_host_week ? esc(d.top_host_week.name) + ' <span class="mono">(' + fmt(d.top_host_week.points) + ' pts)</span>' : 'nobody yet';
  const topVoucher = d.top_voucher_week ? esc(d.top_voucher_week.name) + ' <span class="mono">(' + d.top_voucher_week.count + ' vouches)</span>' : 'nobody yet';
  el.innerHTML =
    '<div class="stat-grid">' +
      '<div class="stat"><div class="val">' + fmt(d.total_members) + '</div><div class="lbl">Total members</div></div>' +
      '<div class="stat"><div class="val">' + fmt(d.total_vouches_all_time) + '</div><div class="lbl">Vouches all time</div></div>' +
      '<div class="stat"><div class="val">' + fmt(d.vouches_this_week) + '</div><div class="lbl">Vouches this week</div></div>' +
      '<div class="stat"><div class="val">' + fmt(d.points_this_week) + '</div><div class="lbl">Points this week</div></div>' +
      '<div class="stat"><div class="val">' + d.live_now_count + '</div><div class="lbl">Live right now</div></div>' +
      '<div class="stat"><div class="val">' + d.open_tickets + '</div><div class="lbl">Open tickets</div></div>' +
    '</div>' +
    '<div class="card"><h3>Top host this week</h3><p style="font-size:14px">' + topHost + '</p></div>' +
    '<div class="card"><h3>Top voucher this week</h3><p style="font-size:14px">' + topVoucher + '</p></div>';
}

/* ── Members ── */
let MEMBERS = [];
let memberSort = 'total';
async function loadMembers(){
  const el = document.getElementById('members-list');
  let d;
  try { d = await api('/api/members'); } catch(e){ return; }
  MEMBERS = d.members || [];
  document.getElementById('members-sub').textContent = d.count + ' member' + (d.count===1?'':'s') + ' with a vouch.';
  renderMembers();
}
function switchMemberSort(key, el){
  memberSort = key;
  document.querySelectorAll('#m-tabs .tab').forEach(function(t){ t.classList.remove('active'); });
  el.classList.add('active');
  renderMembers();
}
function renderMembers(){
  const q = document.getElementById('m-q').value.toLowerCase().trim();
  let rows = MEMBERS.slice();
  if(memberSort !== 'total'){
    rows = rows.filter(function(m){ return (m.totals[memberSort]||0) > 0; });
    rows.sort(function(a,b){ return (b.totals[memberSort]||0) - (a.totals[memberSort]||0); });
  }
  if(q) rows = rows.filter(function(m){ return (m.name||'').toLowerCase().indexOf(q) !== -1 || m.uid.indexOf(q) !== -1; });
  const el = document.getElementById('members-list');
  if(!rows.length){ el.innerHTML = '<div class="empty">' + (q ? 'Nobody matches that search.' : 'No members yet.') + '</div>'; return; }
  el.innerHTML = rows.map(function(m, i){
    const pic = m.avatar ? '<img alt="" src="' + m.avatar + '">' : '<span class="ph">' + esc((m.name||'?').slice(0,1).toUpperCase()) + '</span>';
    const value = memberSort === 'total' ? m.total : (m.totals[memberSort]||0);
    const rank = m.rank ? esc(m.rank.name) + ' · ' + esc(m.rank.category) : 'No rank yet';
    return '<a class="row-link' + (m.is_me?' me':'') + '" href="?tab=profile&uid=' + encodeURIComponent(m.uid) +
      '" onclick="return gotoProfile(\\''+m.uid+'\\', event)"><span class="pos">#' + (i+1) + '</span>' +
      '<span class="who" style="flex:1"><span class="ph" style="display:none"></span>' + pic +
      '<span><span class="nm">' + esc(m.resolved ? m.name : 'Unknown member') + (m.is_me?'<span class="tag">you</span>':'') +
      (m.badge ? ' ' + topBadgeImg(m.badge) : '') + '</span>' +
      '<div class="rk">' + rank + '</div></span></span>' +
      '<span class="pts"><b>' + fmt(value) + '</b><span>points</span></span></a>';
  }).join('');
}

/* ── Profile ── */
let MY_ID = '';
let MY_USERNAME = '';
function gotoProfile(uid, ev){
  if(ev) ev.preventDefault();
  if(uid === MY_ID){
    window.CURRENT_VIEWING = '';
    const url = new URL(window.location); url.searchParams.set('tab','profile'); url.searchParams.delete('uid');
    history.replaceState(null, '', url);
  } else {
    window.CURRENT_VIEWING = uid;
    const url = new URL(window.location); url.searchParams.set('tab','profile'); url.searchParams.set('uid', uid);
    history.replaceState(null, '', url);
  }
  loaded.profile = true;
  showTab('profile');
  loadProfile();
  return false;
}
function topBadgeImg(badge, cls){
  if(!badge) return '';
  return '<img class="' + (cls||'top-badge') + '" src="/badge-icon/' + badge.icon + '.png" ' +
    'alt="' + esc(badge.name) + '" title="' + esc(badge.name) + ' - ' + badge.threshold + '+ events hosted">';
}
function renderBadges(b){
  document.getElementById('profile-hero-badge').innerHTML = b && b.top ? ' ' + topBadgeImg(b.top, 'top-badge-lg') : '';
}
function renderStreak(s, dmOptedOut){
  const el = document.getElementById('streak-card');
  if(!s){ el.style.display = 'none'; return; }
  el.style.display = 'block';
  let msg;
  if(s.current === 0){
    msg = s.last_at ? "Streak broken - it's been more than 24h since the last /host." : 'No streak going. Run /host to start one.';
  } else if(s.at_risk){
    const h = s.hours_left;
    msg = 'Breaks 24h after the last /host. ' + (h <= 0 ? 'Run /host now to keep it alive.' : 'About ' + h + ' hour' + (h===1?'':'s') + ' left.');
  } else {
    msg = 'Last hosted ' + timeAgo(s.last_at) + '. Run /host again within 24h to keep it going.';
  }
  el.innerHTML = '<div class="streak-top"><span class="streak-num">' + s.current + '</span>' +
    '<span class="streak-word">host streak</span>' +
    '<span class="streak-best">best ' + s.longest + ' · ' + s.total_runs + ' total /host runs</span></div>' +
    '<div class="streak-msg' + (s.at_risk?' warn':'') + '">' + msg + '</div>';
}
function rivalsHTML(r){
  if(!r || (!r.above && !r.below)) return '';
  let out = '<div class="rivals">';
  if(r.above) out += rivalChip(r.above, 'behind');
  if(r.below) out += rivalChip(r.below, 'ahead of');
  return out + '</div>';
}
function rivalChip(r, word){
  const label = '<b>' + fmt(r.gap) + '</b> ' + word + ' ' + esc(r.name);
  return r.uid ? '<a class="rival" href="?tab=profile&uid=' + encodeURIComponent(r.uid) + '" onclick="return gotoProfile(\\''+r.uid+'\\', event)">' + label + '</a>'
               : '<span class="rival">' + label + '</span>';
}
function goalsHTML(c){
  if(!c.goals || !c.goals.length) return '';
  const unit = c.metric === 'vouches' ? 'vouches' : 'points';
  const rows = c.goals.slice(0,3).map(function(g){
    const routes = (g.routes||[]).filter(function(r){ return r.need > 0; })
      .map(function(r){ return '<span class="route"><b>' + r.need + '</b> ' + esc(r.event) + '</span>'; }).join('');
    return '<div class="goal"><div class="g-top"><b>' + esc(g.role) + '</b> needs ' + fmt(g.short) + ' more ' + unit + '</div>' +
      '<div class="routes">' + routes + '</div></div>';
  }).join('');
  return '<div class="goals">' + rows + '</div>';
}
async function loadProfile(){
  const viewing = window.CURRENT_VIEWING || VIEWING;
  const ownOnly = document.getElementById('profile-own-only');
  ownOnly.style.display = viewing ? 'none' : 'block';
  document.getElementById('profile-hero-name').textContent = viewing ? (window.CURRENT_VIEWING_NAME || VIEWING_NAME) : MY_USERNAME;
  document.getElementById('profile-hero-sub').textContent = viewing ? 'Their vouch record.' : 'Here is where you stand.';
  document.getElementById('activity-heading').textContent = viewing ? 'Activity' : 'Your activity';

  let d;
  try {
    const url = viewing ? '/api/profile/' + viewing : '/api/profile';
    d = await api(url);
    if(d.error){
      document.getElementById('cats').innerHTML = '<div class="card"><div class="empty">' + esc(d.error) + '</div></div>';
      document.getElementById('streak-card').style.display = 'none';
      return;
    }
  } catch(e){ return; }

  document.getElementById('s-total').textContent = fmt(d.total);
  document.getElementById('s-week').textContent = fmt(d.this_week);
  document.getElementById('s-vouches').textContent = d.categories.reduce(function(a,c){ return a + c.vouches; }, 0);

  const diff = d.this_week - d.last_week;
  const delta = document.getElementById('s-delta');
  if(d.last_week === 0 && d.this_week === 0){ delta.textContent = 'no activity yet'; delta.className = 'delta flat'; }
  else if(diff > 0){ delta.textContent = '+' + fmt(diff) + ' vs last week'; delta.className = 'delta up'; }
  else if(diff < 0){ delta.textContent = fmt(diff) + ' vs last week'; delta.className = 'delta down'; }
  else { delta.textContent = 'same as last week'; delta.className = 'delta flat'; }

  document.getElementById('cats').innerHTML = d.categories.map(function(c){
    const color = CAT_COLORS[c.key] || '#7fc2b8';
    const rk = c.rank;
    const bar = rk
      ? '<div class="rank-top"><span class="rank-name">' + esc(rk.current || 'No rank yet') + '</span>' +
        '<span class="rank-next">' + (rk.next ? fmt(rk.remaining) + ' to ' + esc(rk.next) : 'Top rank reached') + '</span></div>' +
        '<div class="rank-bar"><div class="rank-fill" style="width:' + rk.pct + '%;background:' + color + '"></div></div>'
      : '<div class="rank-next">No rank ladder set for this category.</div>';
    const pos = c.position ? '<span class="cat-pos">#' + c.position + ' of ' + c.of + '</span>' : '<span class="cat-pos">unranked</span>';
    const chips = Object.keys(c.events).map(function(e){ return '<span class="chip">' + esc(e) + ' <b>' + c.events[e] + '</b></span>'; }).join('');
    return '<div class="card"><div class="cat-head"><span class="cat-name" style="color:' + color + '">' + esc(c.name) + '</span>' + pos + '</div>' +
      bar + '<div class="cat-stats"><div><b>' + fmt(c.points) + '</b>points</div><div><b>' + c.vouches + '</b>vouches</div></div>' +
      (chips ? '<div class="chips">' + chips + '</div>' : '') + rivalsHTML(c.rivals) + goalsHTML(c) + '</div>';
  }).join('');

  renderStreak(d.streak, d.streak_dm_opt_out);
  renderBadges(d.badges);
  if(!viewing){
    document.getElementById('pref-streak').checked = !d.streak_dm_opt_out;
    document.getElementById('pref-rankup').checked = !d.rank_up_dm_opt_out;
  }

  const b = d.bests || {};
  const lastVouch = d.last_vouch ? (esc(d.last_vouch.event) + ' ' + timeAgo(d.last_vouch.time)) : 'none yet';
  document.getElementById('bests').innerHTML =
    '<div><b>' + (b.best_day ? fmt(b.best_day.points) : '0') + '</b>best day' + (b.best_day ? ' (' + b.best_day.date + ')' : '') + '</div>' +
    '<div><b>' + (b.active_days || 0) + '</b>active days</div>' +
    '<div><b>' + (b.total_vouches || 0) + '</b>vouches</div>' +
    '<div><b>' + (b.first_seen || '-') + '</b>first vouch</div>' +
    '<div><b>' + lastVouch + '</b>last vouch</div>';

  renderChart(d.chart);
  if(!viewing) loadHistory();
}
function renderChart(c){
  const holder = document.getElementById('chart');
  if(!c || !c.labels){ holder.innerHTML = '<div class="empty">No activity yet.</div>'; return; }
  const cats = ['pve','security','support'];
  const all = cats.reduce(function(a,k){ return a.concat(c.series[k]||[]); }, []);
  const max = Math.max(1, Math.max.apply(null, all));
  if(max <= 1 && all.every(function(v){ return v === 0; })){
    holder.innerHTML = '<div class="empty">No points in the last 30 days.</div>';
    document.getElementById('chart-legend').innerHTML = '';
    return;
  }
  const W = 760, H = 230, PL = 42, PR = 12, PT = 14, PB = 26;
  const n = c.labels.length;
  const x = function(i){ return PL + (i*(W-PL-PR))/Math.max(1,n-1); };
  const y = function(v){ return PT + (H-PT-PB)*(1 - v/max); };
  let g = '';
  for(let i=0;i<=4;i++){
    const v = max*i/4, yy = y(v);
    g += '<line x1="'+PL+'" y1="'+yy+'" x2="'+(W-PR)+'" y2="'+yy+'" stroke="#2a2432" stroke-width="1"/>' +
         '<text x="'+(PL-8)+'" y="'+(yy+4)+'" fill="#6b5f78" font-size="11" text-anchor="end">' + fmt(Math.round(v)) + '</text>';
  }
  const step = Math.max(1, Math.floor(n/5));
  for(let i=0;i<n;i+=step){
    g += '<text x="'+x(i)+'" y="'+(H-7)+'" fill="#6b5f78" font-size="11" text-anchor="middle">' + c.labels[i].slice(5) + '</text>';
  }
  let lines = '';
  cats.forEach(function(k){
    const pts = (c.series[k]||[]).map(function(v,i){ return x(i)+','+y(v); }).join(' ');
    lines += '<polyline points="'+pts+'" fill="none" stroke="'+CAT_COLORS[k]+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
  });
  holder.innerHTML = '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet" role="img">' + g + lines + '</svg>';
  document.getElementById('chart-legend').innerHTML = cats.map(function(k){
    const tot = (c.series[k]||[]).reduce(function(a,v){ return a+v; }, 0);
    return '<span><i style="background:'+CAT_COLORS[k]+'"></i>'+CAT_NAMES[k]+' '+fmt(Math.round(tot*10)/10)+'</span>';
  }).join('');
}
function histQuery(){
  const p = new URLSearchParams();
  const cat = document.getElementById('f-cat').value;
  const days = document.getElementById('f-days').value;
  const q = document.getElementById('f-q').value.trim();
  if(cat) p.set('category', cat);
  if(days && days !== '0') p.set('days', days);
  if(q) p.set('q', q);
  return p.toString();
}
async function loadHistory(){
  const holder = document.getElementById('history');
  let d;
  try { d = await api('/api/profile/history?' + histQuery()); } catch(e){ holder.innerHTML = '<div class="empty">Could not load history.</div>'; return; }
  document.getElementById('hist-sum').textContent = d.total + ' vouches, ' + fmt(d.points) + ' points';
  if(!d.rows.length){ holder.innerHTML = '<div class="empty">Nothing matches those filters.</div>'; return; }
  holder.innerHTML = '<table><thead><tr><th>Date</th><th>Event</th><th>Category</th><th>Points</th><th>Given by</th></tr></thead><tbody>' +
    d.rows.map(function(r){
      return '<tr><td style="white-space:nowrap;color:var(--muted);font-size:12px">' + String(r.time||'').substring(0,10) + '</td>' +
        '<td>' + esc(r.event) + (r.backfilled ? ' <span style="font-size:10px;color:var(--amber)">[added]</span>' : '') + '</td>' +
        '<td style="color:' + (CAT_COLORS[r.category]||'#6b5f78') + '">' + esc(r.category_name) + '</td>' +
        '<td class="mono">+' + fmt(r.points) + '</td>' +
        '<td style="color:var(--muted);font-size:12px">' + esc(r.by || '-') + '</td></tr>';
    }).join('') + '</tbody></table>';
}
async function savePrefs(){
  const body = {
    streak_dm_opt_out: !document.getElementById('pref-streak').checked,
    rank_up_dm_opt_out: !document.getElementById('pref-rankup').checked,
  };
  await fetch('/api/profile/notification_prefs', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body),
  });
}

/* ── Init ── */
let histTimer = null;
document.addEventListener('DOMContentLoaded', function(){
  MY_ID = "{{ user.id }}";
  MY_USERNAME = "{{ user.username }}";
  window.CURRENT_VIEWING = VIEWING;
  window.CURRENT_VIEWING_NAME = VIEWING_NAME;
  document.getElementById('m-q').addEventListener('input', renderMembers);
  document.getElementById('f-cat').onchange = loadHistory;
  document.getElementById('f-days').onchange = loadHistory;
  document.getElementById('f-q').oninput = function(){ clearTimeout(histTimer); histTimer = setTimeout(loadHistory, 300); };
  document.getElementById('f-export').onclick = function(){ window.location.href = '/api/profile/history.csv?' + histQuery(); };
  showTab(INITIAL_TAB);
});
</script>
</body>
</html>""".replace("__LOGO__", LOGO_SRC)

# ─────────────────────────────────────────────────────────────
# DASHBOARD HTML
# ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Matzys Overseer - Dashboard</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0c1210;--header:#0d1614;--card:#0d1614;--card-2:#152220;
  --border:#233530;--border-2:#324b44;
  --moon:#7fc2b8;--moon-dim:#a8ddd2;--steel:#9c8fe0;--sage:#5fcf9f;--red:#c77a80;--amber:#d1a86a;
  --text:#eef4f2;--muted:#8fa39d;--dim:#5c6f69;
  --mono:ui-monospace,"SF Mono",Consolas,monospace;--sans:'Space Grotesk',-apple-system,"Segoe UI",system-ui,sans-serif;
  --serif:'Cinzel',ui-serif,"Iowan Old Style",Georgia,serif;
  --radius:4px;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100dvh;
  display:flex;flex-direction:column;overflow-x:hidden}
:focus-visible{outline:2px solid var(--moon);outline-offset:2px;border-radius:6px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}

/* ── Header ── */
.header{position:sticky;top:0;z-index:60;background:var(--header);border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:12px;padding:10px 16px;flex-shrink:0}
.icon-btn{background:none;border:none;color:var(--text);cursor:pointer;padding:8px;border-radius:10px;
  display:flex;align-items:center;justify-content:center;line-height:0;transition:background .15s}
.icon-btn:hover{background:rgba(255,255,255,.06)}
.icon-btn svg{width:22px;height:22px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round}
.brand{width:34px;height:34px;border-radius:11px;display:block;object-fit:cover;flex-shrink:0;
  border:1px solid var(--border)}
.spacer{flex:1}

/* Current-server badge */
.pill{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--border);
  border-radius:999px;padding:6px 14px 6px 6px;color:var(--text);font-family:inherit;
  font-size:14px;font-weight:500;max-width:min(52vw,320px)}
.pill img,.pill .fallback{width:30px;height:30px;border-radius:50%;flex-shrink:0;object-fit:cover}
.pill .fallback{background:var(--card-2);display:flex;align-items:center;justify-content:center;
  font-size:12px;font-weight:600;color:var(--muted)}
.pill .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.menu{position:absolute;top:calc(100% + 8px);background:var(--card);border:1px solid var(--border);
  border-radius:14px;padding:6px;min-width:240px;box-shadow:0 18px 40px rgba(0,0,0,.5);display:none;z-index:70}
.menu.open{display:block}
.menu-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:10px;cursor:pointer;
  font-size:14px;color:var(--text);background:none;border:none;width:100%;text-align:left;font-family:inherit;
  text-decoration:none}
.menu-item:hover{background:var(--card-2)}
.menu-item img,.menu-item .fallback{width:26px;height:26px;border-radius:50%}
.menu-item.danger{color:var(--red)}
.menu-label{padding:8px 10px 4px;font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--dim)}
.menu-sep{height:1px;background:var(--border);margin:6px 4px}
.avatar-btn{padding:0;background:none;border:none;cursor:pointer;border-radius:50%;flex-shrink:0}
.avatar-btn img{width:38px;height:38px;border-radius:50%;display:block;border:1px solid var(--border)}
.user-menu-wrap{position:relative}
.user-menu-wrap .menu{right:0}

/* ── Drawer nav ── */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:80;opacity:0;pointer-events:none;transition:opacity .2s}
.overlay.show{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;left:0;height:100dvh;width:264px;background:var(--header);z-index:90;
  border-right:1px solid var(--border);transform:translateX(-100%);transition:transform .22s ease;
  display:flex;flex-direction:column;padding:18px 0}
.drawer.open{transform:none}
.drawer-head{display:flex;align-items:center;gap:10px;padding:0 18px 18px;border-bottom:1px solid var(--border)}
.drawer-head h2{font-size:14px;font-weight:600}
.drawer-head p{font-size:11px;color:var(--dim)}
.nav{padding:14px 10px;flex:1;overflow-y:auto}
.nav-label{font-size:10px;letter-spacing:1.4px;text-transform:uppercase;color:var(--dim);padding:10px 10px 6px}
.nav-item{display:flex;align-items:center;gap:11px;padding:11px 12px;border-radius:11px;cursor:pointer;
  color:var(--muted);font-size:14px;font-weight:500;transition:all .15s}
.nav-item:hover{color:var(--text);background:var(--card)}
.nav-item.active{color:var(--moon);background:rgba(127,194,184,.12)}
.nav-item .ic{width:19px;height:19px;flex-shrink:0}
.menu-item .mi{width:17px;height:17px;flex-shrink:0}
.drawer-foot{padding:14px 18px 0;border-top:1px solid var(--border);font-size:12px;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--sage);display:inline-block;margin-right:7px;
  animation:pulse 2.4s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── Layout ── */
.content{flex:1;padding:28px 20px 40px;max-width:1180px;width:100%;margin:0 auto;position:relative;z-index:1}
.section{display:none}
.section.active{display:block;animation:fade .25s ease}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* ── Hero ── */
.hero{position:relative;padding:26px 0 34px}
.hero::before{content:'';position:absolute;top:-40px;right:-10%;width:340px;height:340px;
  border-radius:50%;background:radial-gradient(circle,rgba(127,194,184,.16),rgba(127,194,184,.02) 55%,transparent 72%);
  pointer-events:none;z-index:-1}
.hero h1{font-family:var(--serif);font-size:clamp(30px,6.5vw,44px);font-weight:500;letter-spacing:.1px;line-height:1.12}
.hero h1 span{color:var(--moon)}
.hero p{margin-top:14px;font-size:clamp(16px,3.6vw,20px);color:var(--muted);font-weight:400;line-height:1.4;max-width:620px}

/* ── Feature cards ── */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.feature{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px;
  display:flex;flex-direction:column;transition:border-color .18s,transform .18s}
.feature:hover{border-color:var(--border-2);transform:translateY(-2px)}
.feature .ic{margin-bottom:18px;color:var(--moon);line-height:0}
.feature .ic svg{width:26px;height:26px}
.feature h3{font-size:20px;font-weight:600;margin-bottom:10px}
.feature p{color:var(--muted);font-size:15px;line-height:1.5;flex:1}
.feature .btn{margin-top:20px;align-self:flex-start}

/* ── Buttons ── */
.btn{padding:11px 20px;border-radius:11px;border:none;cursor:pointer;font-size:14px;font-weight:500;
  font-family:var(--sans);transition:all .15s}
.btn-soft{background:var(--card-2);color:var(--text)}
.btn-soft:hover{background:var(--border-2)}
.btn-primary{background:var(--moon);color:#1a1118}
.btn-primary:hover{background:#d59fb6}
.btn-danger{background:rgba(199,122,128,.14);color:var(--red);border:1px solid rgba(199,122,128,.24)}
.btn-danger:hover{background:rgba(199,122,128,.24)}
.btn-ghost{background:rgba(255,255,255,.05);color:var(--muted);border:1px solid var(--border)}
.btn-ghost:hover{color:var(--text)}
.btn-sm{padding:6px 12px;font-size:12.5px;border-radius:9px}

/* ── Generic surfaces ── */
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:22px}
.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.section-head h2{font-family:var(--serif);font-size:22px;font-weight:500;letter-spacing:.1px}
.card-title{font-size:14px;font-weight:600;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px;margin-bottom:22px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.stat .val{font-family:var(--mono);font-size:28px;font-weight:600}
.stat .lbl{font-size:12.5px;color:var(--muted);margin-top:4px}
.stat .accent{width:3px;height:30px;border-radius:2px;float:right}
.grid-3{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;padding:9px 12px;color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;
  letter-spacing:.9px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:11px 12px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}
.mono{font-family:var(--mono);font-size:12px;color:var(--muted)}
.badge{background:rgba(127,194,184,.15);color:var(--moon);border-radius:7px;padding:4px 10px;font-size:11.5px;
  font-weight:600;font-family:var(--mono)}
.badge.green{background:rgba(95,207,159,.14);color:var(--sage)}
.badge.red{background:rgba(199,122,128,.14);color:var(--red)}
.tabs{display:flex;gap:3px;margin-bottom:18px;background:var(--card);border:1px solid var(--border);
  border-radius:12px;padding:4px;width:fit-content;max-width:100%;overflow-x:auto}
.tab{padding:8px 18px;border-radius:9px;cursor:pointer;font-size:13.5px;font-weight:500;color:var(--muted);
  white-space:nowrap;transition:all .15s}
.tab.active{background:var(--card-2);color:var(--text)}
.cat-tabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.cat-tab{padding:6px 15px;border-radius:999px;font-size:12.5px;font-weight:500;cursor:pointer;
  border:1px solid var(--border);color:var(--muted);transition:all .15s}
.cat-tab.active{border-color:var(--moon);color:var(--moon);background:rgba(127,194,184,.1)}
.form-group{margin-bottom:16px}
.form-group label{display:block;font-size:12.5px;color:var(--muted);margin-bottom:7px;font-weight:500}
.form-group input,.form-group select,textarea{width:100%;background:var(--card-2);border:1px solid var(--border);
  border-radius:11px;padding:11px 13px;color:var(--text);font-size:14px;font-family:var(--sans);outline:none;
  transition:border-color .15s}
.form-group input:focus,.form-group select:focus,textarea:focus{border-color:var(--moon)}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.toggle-wrap{display:flex;align-items:center;gap:12px}
.toggle{position:relative;width:46px;height:26px;cursor:pointer;flex-shrink:0}
.toggle input{opacity:0;width:0;height:0;position:absolute}
.toggle-slider{position:absolute;inset:0;background:var(--border-2);border-radius:26px;transition:.2s}
.toggle input:checked + .toggle-slider{background:var(--sage)}
.toggle-slider:before{content:'';position:absolute;width:20px;height:20px;left:3px;bottom:3px;background:#fff;
  border-radius:50%;transition:.2s}
.toggle input:checked + .toggle-slider:before{transform:translateX(20px)}
.memory-item{display:flex;align-items:center;gap:12px;padding:14px;background:var(--card-2);border-radius:12px;margin-bottom:9px}
.memory-item .text{flex:1;font-size:13.5px;line-height:1.45}
.memory-item .id{font-family:var(--mono);font-size:10.5px;color:var(--dim);margin-top:4px}
.audit-item{display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}
.audit-item:last-child{border-bottom:none}
.audit-dot{width:8px;height:8px;border-radius:50%;margin-top:6px;flex-shrink:0}
.audit-content .main-text{font-size:13.5px;line-height:1.45}
.audit-content .meta{font-size:11.5px;color:var(--dim);margin-top:3px;font-family:var(--mono)}
.times-grid{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.time-chip{background:var(--card-2);border:1px solid var(--border);border-radius:8px;padding:5px 10px;
  font-family:var(--mono);font-size:12px;color:var(--muted)}
.empty{text-align:center;padding:44px 20px;color:var(--dim);font-size:13.5px}
.member{display:flex;align-items:center;gap:10px;min-width:0}
.member img,.member .ph{width:30px;height:30px;border-radius:50%;flex-shrink:0;background:var(--card-2)}
.member .ph{display:flex;align-items:center;justify-content:center;font-size:12px;color:var(--muted);font-weight:600}
.member .who{min-width:0}
.member .nm{font-size:13.5px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.member .id{font-family:var(--mono);font-size:10.5px;color:var(--dim)}
.rank-row{background:var(--card-2);border-radius:12px;padding:14px;margin-bottom:12px}
.rank-top{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:9px;flex-wrap:wrap}
.rank-name{font-size:14px;font-weight:600}
.rank-next{font-size:11.5px;color:var(--muted);font-family:var(--mono)}
.rank-bar{height:7px;border-radius:4px;background:var(--border);overflow:hidden}
.rank-fill{height:100%;border-radius:4px;background:var(--moon);transition:width .4s}
.filters{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:16px;align-items:center}
.filters select,.filters input{background:var(--card-2);border:1px solid var(--border);border-radius:10px;
  padding:9px 12px;color:var(--text);font-size:13px;font-family:var(--sans);outline:none}
.filters input{font-family:var(--mono);min-width:150px}
.filters select:focus,.filters input:focus{border-color:var(--moon)}
.chart-wrap{position:relative;width:100%;overflow:hidden}
.chart-wrap svg{width:100%;height:auto;display:block}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:12px;color:var(--muted)}
.legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:6px}
.cmd-item{display:flex;align-items:center;gap:12px;padding:14px;background:var(--card-2);border-radius:12px;margin-bottom:9px}
.cmd-item .body{flex:1;min-width:0}
.cmd-item .nm{font-family:var(--mono);font-size:13.5px;font-weight:600;color:var(--moon)}
.cmd-item .rp{font-size:12.5px;color:var(--muted);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmd-item .mt{font-size:10.5px;color:var(--dim);margin-top:4px;font-family:var(--mono)}
.off{opacity:.5}
.prefix-wrap{position:relative}
.prefix-wrap span{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--dim);
  font-family:var(--mono);font-size:14px;pointer-events:none}
.prefix-wrap input{padding-left:28px!important;font-family:var(--mono)}
.eco-row{display:flex;gap:9px;align-items:center;margin-bottom:9px}
.eco-row input{background:var(--card-2);border:1px solid var(--border);border-radius:10px;padding:10px 12px;
  color:var(--text);font-size:13.5px;font-family:var(--sans);outline:none;min-width:0}
.eco-row input:focus{border-color:var(--moon)}
.eco-row .nm{flex:1}
.eco-row .num{width:104px;font-family:var(--mono);text-align:right}
.eco-row .del{background:none;border:1px solid var(--border);color:var(--dim);border-radius:10px;
  width:38px;height:38px;flex-shrink:0;cursor:pointer;font-size:16px;line-height:1;transition:all .15s}
.eco-row .del:hover{color:var(--red);border-color:rgba(199,122,128,.4)}
.eco-head{display:flex;gap:9px;padding:0 4px 8px;font-size:11px;letter-spacing:.9px;
  text-transform:uppercase;color:var(--dim)}
.eco-head .nm{flex:1}
.eco-head .num{width:104px;text-align:right}
.eco-head .sp{width:38px;flex-shrink:0}
.eco-actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:14px;align-items:center}
.eco-note{font-size:12.5px;color:var(--muted);line-height:1.5;margin-bottom:14px}
.alert{border-radius:12px;padding:13px 16px;font-size:13.5px;line-height:1.5}
.alert-warn{background:rgba(209,168,106,.1);border:1px solid rgba(209,168,106,.24);color:var(--amber)}
.alert-success{background:rgba(95,207,159,.1);border:1px solid rgba(95,207,159,.24);color:var(--sage)}
.alert-err{background:rgba(199,122,128,.1);border:1px solid rgba(199,122,128,.24);color:var(--red)}
.user-detail{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:22px;margin-top:20px}

/* ── Footer ── */
.footer{position:relative;z-index:1;border-top:1px solid var(--border);padding:22px 20px 30px;text-align:center;color:var(--dim);font-size:13px}
.footer a{color:var(--dim);text-decoration:none;margin:0 4px}
.footer a:hover{color:var(--muted)}
.footer .sep{opacity:.5;margin:0 4px}
@media(max-width:560px){
  .form-row{grid-template-columns:1fr}
  .content{padding:22px 16px 32px}
  .feature{padding:20px}
}

/* ── Persistent sidebar on wide screens - no more hidden-until-clicked drawer ── */
@media (min-width:960px){
  body{display:grid;grid-template-columns:260px 1fr;grid-template-rows:auto 1fr auto;min-height:100dvh}
  .overlay{display:none}
  .drawer{position:sticky;top:0;left:0;transform:none;grid-column:1;grid-row:1 / 4;height:100dvh}
  .header{grid-column:2;grid-row:1}
  .content{grid-column:2;grid-row:2}
  .footer{grid-column:2;grid-row:3}
  .icon-btn{display:none}
  .header .brand{display:none}
}
</style>
</head>
<body>
<div class="overlay" id="overlay" onclick="closeDrawer()"></div>

<!-- DRAWER -->
<aside class="drawer" id="drawer">
  <div class="drawer-head">
    <img class="brand" src="__LOGO__" alt="">
    <div><h2>Matzys Overseer</h2><p>Admin dashboard</p></div>
  </div>
  <nav class="nav">
    <div class="nav-label">Main</div>
    <div class="nav-item active" data-sec="home" onclick="showSection('home',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg> Home</div>
    <div class="nav-item" data-sec="overview" onclick="showSection('overview',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/></svg> Overview</div>
    <div class="nav-item" data-sec="leaderboard" onclick="showSection('leaderboard',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 21V11M12 21V4M19 21v-6"/></svg> Leaderboards</div>
    <a class="nav-item" href="/members" style="text-decoration:none"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg> Member directory</a>
    <div class="nav-item" data-sec="users" onclick="showSection('users',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg> Members</div>
    <div class="nav-label">Bot</div>
    <div class="nav-item" data-sec="activity" onclick="showSection('activity',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg> Site activity</div>
    <div class="nav-item" data-sec="economy" onclick="showSection('economy',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M18 7h2M4 12h4M13 12h7M4 17h9M18 17h2M14 4.5v5M9 9.5v5M14 14.5v5"/></svg> Points &amp; ranks</div>
    <div class="nav-item" data-sec="commands" onclick="showSection('commands',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 9l3 3-3 3M13 15h4M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/></svg> Commands</div>
    <div class="nav-item" data-sec="audit" onclick="showSection('audit',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2M9 2h6v4H9zM8 12h8M8 16h5"/></svg> Audit log</div>
    <div class="nav-item" data-sec="onleave" onclick="showSection('onleave',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2"/></svg> On leave</div>
    <div class="nav-item" data-sec="memories" onclick="showSection('memories',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg> Memories</div>
    <div class="nav-item" data-sec="events" onclick="showSection('events',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2"/></svg> Event schedule</div>
    <div class="nav-item" data-sec="updates" onclick="showSection('updates',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg> Updates</div>
    <div class="nav-item" data-sec="ticketmods" onclick="showSection('ticketmods',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 0 0 1.946-.806 3.42 3.42 0 0 1 4.438 0 3.42 3.42 0 0 0 1.946.806 3.42 3.42 0 0 1 3.138 3.138 3.42 3.42 0 0 0 .806 1.946 3.42 3.42 0 0 1 0 4.438 3.42 3.42 0 0 0-.806 1.946 3.42 3.42 0 0 1-3.138 3.138 3.42 3.42 0 0 0-1.946.806 3.42 3.42 0 0 1-4.438 0 3.42 3.42 0 0 0-1.946-.806 3.42 3.42 0 0 1-3.138-3.138 3.42 3.42 0 0 0-.806-1.946 3.42 3.42 0 0 1 0-4.438 3.42 3.42 0 0 0 .806-1.946 3.42 3.42 0 0 1 3.138-3.138z"/></svg> Ticket mods</div>
    <div class="nav-item" data-sec="whitelist" onclick="showSection('whitelist',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 15a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM5.5 21a6.5 6.5 0 0 1 13 0M17 8l1.5 1.5L21.5 6"/></svg> Whitelist</div>
    <div class="nav-item" data-sec="rolegrants" onclick="showSection('rolegrants',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 3 7v6c0 5 4 8.5 9 9 5-.5 9-4 9-9V7z"/><path d="m9 12 2 2 4-4"/></svg> Role Grants</div>
    <div class="nav-item" data-sec="settings" onclick="showSection('settings',this)"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3M13 4.5v5M7 9.5v5M13 14.5v5"/></svg> Settings</div>
  </nav>
  <div class="drawer-foot">
    <div><span class="dot"></span><span id="bot-label">Checking bot…</span></div>
  </div>
</aside>

<!-- HEADER -->
<header class="header">
  <button class="icon-btn" onclick="openDrawer()" aria-label="Open menu">
    <svg viewBox="0 0 24 24"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
  </button>
  <img class="brand" src="__LOGO__" alt="">
  <div class="spacer"></div>
  <div class="pill" id="guild-pill">
    <span class="fallback" id="guild-icon">&nbsp;</span>
    <span class="name" id="guild-name">Loading…</span>
  </div>
  <div class="spacer"></div>
  <div class="user-menu-wrap">
    <button class="avatar-btn" onclick="toggleMenu('user-menu')" aria-label="Account">
      <img id="user-avatar" alt="" src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==">
    </button>
    <div class="menu" id="user-menu">
      <div class="menu-label" id="user-handle">Signed in</div>
      <a class="menu-item" href="/"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg> Back to site</a>
      <a class="menu-item" href="/members"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg> Members</a>
      <a class="menu-item" href="/profile"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8"/></svg> My profile</a>
      <div class="menu-item" onclick="showSection('settings')"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3M13 4.5v5M7 9.5v5M13 14.5v5"/></svg> Settings</div>
      <div class="menu-sep"></div>
      <a class="menu-item danger" href="/logout"><svg class="mi" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg> Sign out</a>
    </div>
  </div>
</header>

<main class="content">

  <!-- HOME -->
  <section id="sec-home" class="section active">
    <div class="hero">
      <h1>Welcome <span id="hero-name">there</span>,</h1>
      <p>find commonly used dashboard pages below.</p>
    </div>
    <div class="cards">
      <article class="feature">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg></div>
        <h3>Site activity</h3>
        <p>See how much the dashboard and profiles actually get used, and by whom.</p>
        <button class="btn btn-soft" onclick="showSection('activity')">View activity</button>
      </article>
      <article class="feature">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M18 7h2M4 12h4M13 12h7M4 17h9M18 17h2M14 4.5v5M9 9.5v5M14 14.5v5"/></svg></div>
        <h3>Points &amp; ranks</h3>
        <p>Change what each event is worth and where every rank role unlocks.</p>
        <button class="btn btn-soft" onclick="showSection('economy')">Points &amp; ranks</button>
      </article>
      <article class="feature">
        <div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 9l3 3-3 3M13 15h4M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/></svg></div>
        <h3>Custom commands</h3>
        <p>Build your own <code style="font-family:var(--mono);color:var(--moon)">?commands</code> - pick a name, write the reply, and the bot answers instantly.</p>
        <button class="btn btn-soft" onclick="showSection('commands')">Make a command</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 21V11M12 21V4M19 21v-6"/></svg></div>
        <h3>Leaderboards</h3>
        <p>See who is on top for hosting, security and support, ranked by the points your bot has handed out.</p>
        <button class="btn btn-soft" onclick="showSection('leaderboard')">Open leaderboards</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
        <h3>Members</h3>
        <p>Look up any member, add a vouch by hand, or revert one that shouldn't have counted.</p>
        <button class="btn btn-soft" onclick="showSection('users')">Manage members</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2M9 2h6v4H9zM8 12h8M8 16h5"/></svg></div>
        <h3>Audit log</h3>
        <p>Every vouch, who gave it and when. Backfilled entries are marked so you can spot them fast.</p>
        <button class="btn btn-soft" onclick="showSection('audit')">View audit log</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg></div>
        <h3>Memories</h3>
        <p>Teach the bot facts it should keep in mind during chats, and drop the ones it no longer needs.</p>
        <button class="btn btn-soft" onclick="showSection('memories')">Edit memories</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5V12l3 2"/></svg></div>
        <h3>Event schedule</h3>
        <p>Check the ping times for every recurring event so nobody misses a run.</p>
        <button class="btn btn-soft" onclick="showSection('events')">View schedule</button>
      </article>
      <article class="feature">
        <div class="ic"><svg class="" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h9M17 17h3M13 4.5v5M7 9.5v5M13 14.5v5"/></svg></div>
        <h3>Settings</h3>
        <p>Point the bot at the right channels, pick its persona, and switch chat on or off.</p>
        <button class="btn btn-soft" onclick="showSection('settings')">Open settings</button>
      </article>
    </div>
  </section>

  <!-- OVERVIEW -->
  <section id="sec-overview" class="section">
    <div class="section-head">
      <h2>Overview</h2>
      <div><span class="badge" id="persona-badge">default</span> <span class="badge green" id="chat-badge">Chat on</span></div>
    </div>
    <div class="stat-grid">
      <div class="stat"><div class="accent" style="background:var(--moon)"></div><div class="val" id="stat-users">-</div><div class="lbl">Total members</div></div>
      <div class="stat"><div class="accent" style="background:var(--sage)"></div><div class="val" id="stat-vouches">-</div><div class="lbl">Total vouches</div></div>
      <div class="stat"><div class="accent" style="background:var(--steel)"></div><div class="val" id="stat-memories">-</div><div class="lbl">Memories saved</div></div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div class="section-head" style="margin-bottom:14px">
        <div class="card-title" style="margin:0">Points awarded over time</div>
        <select id="chart-days" onchange="loadChart()"
          style="background:var(--card-2);border:1px solid var(--border);border-radius:10px;padding:7px 11px;
          color:var(--text);font-size:12.5px;font-family:var(--sans);outline:none">
          <option value="14">Last 14 days</option>
          <option value="30" selected>Last 30 days</option>
          <option value="90">Last 90 days</option>
        </select>
      </div>
      <div class="chart-wrap" id="chart"><div class="empty">Loading…</div></div>
      <div class="legend" id="chart-legend"></div>
    </div>
    <div class="grid-3">
      <div class="card" id="ov-host"></div>
      <div class="card" id="ov-security"></div>
      <div class="card" id="ov-support"></div>
    </div>
  </section>

  <!-- LEADERBOARD -->
  <section id="sec-leaderboard" class="section">
    <div class="section-head"><h2>Leaderboards</h2></div>
    <div class="tabs">
      <div class="tab active" onclick="switchLbTab('pve',this)">Host</div>
      <div class="tab" onclick="switchLbTab('security',this)">Security</div>
      <div class="tab" onclick="switchLbTab('support',this)">Support</div>
      <div class="tab" onclick="switchLbTab('givers',this)">Vouchers</div>
    </div>
    <div class="filters" id="lb-giver-range" style="display:none">
      <select id="lb-days" onchange="loadGiverBoard()">
        <option value="0">All time</option>
        <option value="7">Last 7 days</option>
        <option value="30">Last 30 days</option>
        <option value="90">Last 90 days</option>
      </select>
    </div>
    <div class="card"><div class="table-wrap" id="lb-table-wrap"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- USERS -->
  <section id="sec-users" class="section">
    <div class="section-head">
      <h2>Members</h2>
      <input id="user-search" placeholder="Search name or ID" oninput="searchUsers()"
        style="background:var(--card-2);border:1px solid var(--border);border-radius:11px;padding:10px 14px;
        color:var(--text);font-family:var(--mono);font-size:13px;outline:none;min-width:220px">
    </div>
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Member</th><th>Host</th><th>Security</th><th>Support</th><th>Total</th><th></th></tr></thead>
          <tbody id="users-table"><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
        </table>
      </div>
    </div>

    <div class="user-detail" id="user-detail-panel" style="display:none">
      <div class="section-head" style="margin-bottom:14px">
        <h2 style="font-size:18px" id="detail-name">Member</h2>
        <button class="btn btn-ghost btn-sm" onclick="closeDetail()">Close</button>
      </div>
      <div class="cat-tabs" id="detail-cat-tabs"></div>
      <div id="detail-cat-content"></div>
      <div class="card" style="margin-top:20px;background:var(--card-2)">
        <div class="card-title">Add a vouch</div>
        <div class="form-row">
          <div class="form-group"><label>Category</label>
            <select id="add-cat" onchange="populateEvents()">
              <option value="pve">Host</option><option value="security">Security</option><option value="support">Support</option>
            </select>
          </div>
          <div class="form-group"><label>Event</label><select id="add-event"></select></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Count</label><input id="add-count" type="number" min="1" value="1"></div>
          <div class="form-group" style="display:flex;align-items:flex-end">
            <button class="btn btn-primary" style="width:100%" onclick="submitAddVouch()">Add vouch</button>
          </div>
        </div>
        <div id="add-result"></div>
      </div>
    </div>
  </section>

  <!-- AUDIT -->
  <section id="sec-audit" class="section">
    <div class="section-head">
      <h2>Audit log</h2>
      <button class="btn btn-ghost btn-sm" onclick="exportAudit()">Export CSV</button>
    </div>
    <div class="filters">
      <select id="f-cat" onchange="loadAudit()">
        <option value="">All categories</option>
        <option value="pve">Host</option><option value="security">Security</option><option value="support">Support</option>
      </select>
      <select id="f-days" onchange="loadAudit()">
        <option value="0">All time</option><option value="7">Last 7 days</option>
        <option value="30">Last 30 days</option><option value="90">Last 90 days</option>
      </select>
      <input id="f-q" placeholder="Search event, name or ID" oninput="debouncedAudit()">
      <button class="btn btn-ghost btn-sm" onclick="clearAuditFilters()">Clear</button>
    </div>
    <div class="card"><div id="audit-list"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- ON LEAVE -->
  <section id="sec-onleave" class="section">
    <div class="section-head"><h2>On leave</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Currently on leave</div>
      <div id="onleave-current"><div class="empty">Loading…</div></div>
    </div>
    <div class="card">
      <div class="card-title">History</div>
      <div id="onleave-history"><div class="empty">Loading…</div></div>
    </div>
  </section>

  <!-- MEMORIES -->
  <section id="sec-memories" class="section">
    <div class="section-head"><h2>Memories</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Add a memory</div>
      <div class="form-group">
        <textarea id="new-memory-text" rows="3" placeholder="Something the bot should remember"></textarea>
      </div>
      <button class="btn btn-primary" onclick="addMemory()">Save memory</button>
      <div id="memory-result" style="margin-top:12px"></div>
    </div>
    <div class="card"><div id="memories-list"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- EVENTS -->
  <section id="sec-events" class="section">
    <div class="section-head"><h2>Event schedule</h2></div>
    <div id="events-content"><div class="empty">Loading…</div></div>
  </section>

  <!-- UPDATES -->
  <section id="sec-updates" class="section">
    <div class="section-head"><h2>Bot updates</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Post an update</div>
      <div class="form-group">
        <textarea id="new-update-text" rows="4" placeholder="What changed?"></textarea>
      </div>
      <button class="btn btn-primary" onclick="postUpdate()">Post to Discord</button>
      <div id="update-post-result" style="margin-top:12px"></div>
    </div>
    <div class="card"><div id="updates-list"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- TICKET MODS -->
  <section id="sec-ticketmods" class="section">
    <div class="section-head"><h2>Ticket mods</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Add a ticket mod role</div>
      <div class="form-group"><label>Exact role name</label>
        <input type="text" id="new-ticketmod-name" placeholder="e.g. Ticket Support" maxlength="100">
      </div>
      <button class="btn btn-primary" onclick="addTicketMod()">Add role</button>
      <div id="ticketmod-result" style="margin-top:12px"></div>
    </div>
    <div class="card">
      <div class="card-title">Roles with ticket access</div>
      <div class="eco-note">Anyone with Manage Server always has ticket access. Roles added here get it too, without needing full admin. Role names must match your Discord roles exactly.</div>
      <div id="ticketmods-list"><div class="empty">Loading…</div></div>
    </div>
  </section>

  <!-- ANTI-NUKE WHITELIST -->
  <section id="sec-whitelist" class="section">
    <div class="section-head"><h2>Anti-nuke whitelist</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Add a trusted user</div>
      <div class="form-group"><label>Discord user ID</label>
        <input type="text" id="new-whitelist-id" class="mono" placeholder="e.g. 123456789012345678" maxlength="32">
      </div>
      <div class="form-group"><label>Name (optional, for your reference)</label>
        <input type="text" id="new-whitelist-name" placeholder="e.g. Nico" maxlength="100">
      </div>
      <button class="btn btn-primary" onclick="addWhitelist()">Add to whitelist</button>
      <div id="whitelist-result" style="margin-top:12px"></div>
    </div>
    <div class="card">
      <div class="card-title">Exempt from anti-nuke</div>
      <div class="eco-note">Deletions by anyone on this list never count toward the anti-nuke threshold.</div>
      <div id="whitelist-list"><div class="empty">Loading…</div></div>
    </div>
  </section>

  <!-- ROLE GRANTS -->
  <section id="sec-rolegrants" class="section">
    <div class="section-head"><h2>Role grants</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Whitelist role grants</div>
      <div class="form-group"><label>Exact role name that can use /giverole</label>
        <input type="text" id="new-rolegrant-granter" placeholder="e.g. Senior Mod" maxlength="100">
      </div>
      <div class="form-group"><label>Exact role name they can grant</label>
        <input type="text" id="new-rolegrant-role" placeholder="e.g. Junior Mod" maxlength="100">
      </div>
      <button class="btn btn-primary" onclick="addRoleGrant()">Add role grant</button>
      <div id="rolegrant-result" style="margin-top:12px"></div>
    </div>
    <div class="card">
      <div class="card-title">Who can grant what</div>
      <div class="eco-note">Anyone holding the role on the left can use /giverole and /takerole to hand out (or take back) the roles on the right - never any other roles, even ones that would normally sit below it in the server's role hierarchy.</div>
      <div id="rolegrant-list"><div class="empty">Loading…</div></div>
    </div>
  </section>

  <!-- SITE ACTIVITY -->
  <section id="sec-activity" class="section">
    <div class="section-head">
      <h2>Site activity</h2>
      <select id="act-days" onchange="loadActivity()"
        style="background:var(--card-2);border:1px solid var(--border);border-radius:10px;padding:8px 12px;
        color:var(--text);font-size:13px;font-family:var(--sans);outline:none">
        <option value="7">Last 7 days</option>
        <option value="30" selected>Last 30 days</option>
        <option value="90">Last 90 days</option>
      </select>
    </div>
    <div class="stat-grid" id="act-stats"></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Page views and visitors</div>
      <div class="chart-wrap" id="act-chart"><div class="empty">Loading...</div></div>
      <div class="legend" id="act-legend"></div>
    </div>
    <div class="card">
      <div class="card-title">Who is using it</div>
      <div class="table-wrap" id="act-people"><div class="empty">Loading...</div></div>
    </div>
  </section>

  <!-- ECONOMY -->
  <section id="sec-economy" class="section">
    <div class="section-head"><h2>Points &amp; ranks</h2></div>
    <div class="tabs" id="eco-tabs">
      <div class="tab active" data-eco="pve">Host</div>
      <div class="tab" data-eco="security">Security</div>
      <div class="tab" data-eco="support">Support</div>
    </div>

    <div class="card" style="margin-bottom:16px">
      <div class="card-title">Event points</div>
      <div class="eco-note" id="ev-note">What each vouch is worth in this category, and its cooldown per target.</div>
      <div class="eco-head"><span class="nm">Event</span><span class="num">Points</span><span class="num">Cooldown (min)</span><span class="sp"></span></div>
      <div id="ev-rows"></div>
      <div class="eco-actions">
        <button class="btn btn-ghost btn-sm" id="ev-add">Add event</button>
        <button class="btn btn-primary" id="ev-save">Save event points</button>
        <button class="btn btn-ghost btn-sm" id="ev-reset">Reset to defaults</button>
      </div>
      <div id="ev-result"></div>
    </div>

    <div class="card">
      <div class="card-title">Rank ladder</div>
      <div class="eco-note" id="rk-note">Role names must match your Discord roles exactly.</div>
      <div class="eco-head"><span class="nm">Role name</span><span class="num" id="rk-unit">Unlocks at</span><span class="sp"></span></div>
      <div id="rk-rows"></div>
      <div class="eco-actions">
        <button class="btn btn-ghost btn-sm" id="rk-add">Add rank</button>
        <button class="btn btn-primary" id="rk-save">Save rank ladder</button>
        <button class="btn btn-ghost btn-sm" id="rk-reset">Reset to defaults</button>
      </div>
      <div id="rk-result"></div>
    </div>
  </section>

  <!-- COMMANDS -->
  <section id="sec-commands" class="section">
    <div class="section-head"><h2>Custom commands</h2></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title" id="cmd-form-title">Create a command</div>
      <div class="form-row">
        <div class="form-group"><label>Command name</label>
          <div class="prefix-wrap"><span>?</span><input id="cmd-name" placeholder="rules" maxlength="24"></div>
        </div>
        <div class="form-group"><label>Embed title (optional)</label>
          <input id="cmd-title" placeholder="Server rules" maxlength="200">
        </div>
      </div>
      <div class="form-group"><label>Response</label>
        <textarea id="cmd-response" rows="4" maxlength="1900"
          placeholder="What the bot replies with. You can use {user} for the person who ran it."></textarea>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Send as embed</label>
          <div class="toggle-wrap"><label class="toggle"><input type="checkbox" id="cmd-embed">
            <span class="toggle-slider"></span></label>
            <span style="font-size:13px;color:var(--muted)">Nicer formatting, coloured bar</span></div>
        </div>
        <div class="form-group"><label>Embed colour</label>
          <input id="cmd-color" type="color" value="#7fc2b8" style="height:44px;padding:4px">
        </div>
      </div>
      <button class="btn btn-primary" onclick="saveCommand()">Save command</button>
      <button class="btn btn-ghost" onclick="resetCommandForm()" style="margin-left:8px">Reset</button>
      <div id="cmd-result"></div>
    </div>
    <div class="card"><div id="cmd-list"><div class="empty">Loading…</div></div></div>
  </section>

  <!-- SETTINGS -->
  <section id="sec-settings" class="section">
    <div class="section-head"><h2>Settings</h2></div>
    <div class="grid-3" style="margin-bottom:16px">
      <div class="card">
        <div class="card-title">AI chat</div>
        <div class="toggle-wrap">
          <label class="toggle"><input type="checkbox" id="chat-toggle" onchange="toggleChat()"><span class="toggle-slider"></span></label>
          <span id="chat-toggle-label" style="font-size:13.5px;color:var(--muted)">Chat is on</span>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Rank roles</div>
        <p style="font-size:13px;color:var(--muted);line-height:1.5;margin-bottom:14px">
          Recheck every member's points and hand out the right rank role.</p>
        <button class="btn btn-soft" id="resync-btn" onclick="resyncRoles()">Resync all roles</button>
        <div id="resync-result"></div>
      </div>
      <div class="card">
        <div class="card-title">Persona</div>
        <div class="form-group" style="margin:0">
          <select id="persona-select" onchange="savePersona()">
            <option value="default">default</option><option value="hype">hype</option>
            <option value="chill">chill</option><option value="sarcastic">sarcastic</option>
            <option value="formal">formal</option>
          </select>
        </div>
      </div>
    </div>
    <div class="grid-3">
      <div class="card">
        <div class="card-title">Channels</div>
        <div class="form-group"><label>Host vouch channel ID</label><input id="cfg-pve" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Security vouch channel ID</label><input id="cfg-security" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Support vouch channel ID</label><input id="cfg-support" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Live leaderboard channel ID</label><input id="cfg-lb" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Audit log channel ID</label><input id="cfg-audit" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>Event ping channel ID</label><input id="cfg-events" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>General chat channel ID</label><input id="cfg-chime" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>On-leave button channel ID</label><input id="cfg-leave-btn" class="mono" placeholder="Channel ID"></div>
        <div class="form-group"><label>On-leave log channel ID</label><input id="cfg-leave-log" class="mono" placeholder="Channel ID"></div>
      </div>
      <div class="card" style="display:flex;flex-direction:column;justify-content:space-between">
        <div>
          <div class="card-title">Save channels</div>
          <div class="alert alert-warn">Channel changes apply after you restart the bot in Railway.</div>
        </div>
        <div>
          <button class="btn btn-primary" style="margin-top:16px" onclick="saveSettings()">Save all settings</button>
          <div id="settings-result" style="margin-top:12px"></div>
        </div>
      </div>
    </div>
  </section>

</main>

<footer class="footer">
  <span id="footer-copy">&copy; 2026 Matzys Overseer</span>
  <span class="sep">&middot;</span><a href="#" onclick="return false">Terms</a>
  <span class="sep">&middot;</span><a href="#" onclick="return false">Privacy</a>
  <span class="sep">&middot;</span><a href="/logout">Sign out</a>
</footer>

<script>
// ── State ──
let lbData = {};
let usersData = [];
let currentDetailUid = null;
let currentDetailData = null;
let currentDetailCat = 'pve';
let currentLbCat = 'pve';
let me = null;

let CATEGORY_EVENTS = {
  pve: {"Enmity":1.5,"Elder":2,"Titus":3,"Hellmode":15,"Deep Champion":15,"Diluvian W (25)":3,"Diluvian W (50)":10,"Parasol":5,"Layer 2 (1)":3,"Layer 2 (2)":7,"Other Bosses":1},
  security: {"Security Vouch":1,"Depths Vouch":1.5,"Defense Vouch":1,"Depths Defense Vouch":1.5},
  support: {"Support Vouch":1,"Backup Vouch":2,"Depths Safe Vouch":5}
};
const CAT_NAMES = {pve:'Host',security:'Security',support:'Support'};
const CAT_COLORS = {pve:'var(--moon)',security:'var(--steel)',support:'var(--sage)'};

// ── Helpers ──
async function api(path, opts={}) {
  const r = await fetch(path, {headers:{'Content-Type':'application/json'},...opts});
  if(r.status === 401){ window.location.href = '/login'; return {}; }
  return r.json();
}
function fmt(n){return typeof n==='number'?n.toLocaleString('en-US',{maximumFractionDigits:1}):n;}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function memberCell(u){
  const pic = u.avatar ? '<img alt="" src="'+u.avatar+'">'
                       : '<span class="ph">'+esc((u.name||'?').slice(0,1).toUpperCase())+'</span>';
  const nm = u.resolved ? esc(u.name) : 'Unknown member';
  return '<div class="member">'+pic+'<div class="who"><div class="nm">'+nm+
         '</div><div class="id">'+u.uid+'</div></div></div>';
}
function showAlert(el,msg,type='success'){
  el.innerHTML = '<div class="alert alert-'+type+'" style="margin-top:10px">'+msg+'</div>';
  setTimeout(()=>el.innerHTML='',3500);
}

// ── Drawer + menus ──
function openDrawer(){document.getElementById('drawer').classList.add('open');document.getElementById('overlay').classList.add('show');}
function closeDrawer(){document.getElementById('drawer').classList.remove('open');document.getElementById('overlay').classList.remove('show');}
function toggleMenu(id){
  document.querySelectorAll('.menu').forEach(m=>{ if(m.id!==id) m.classList.remove('open'); });
  document.getElementById(id).classList.toggle('open');
}
document.addEventListener('click',e=>{
  if(!e.target.closest('.menu') && !e.target.closest('.pill') && !e.target.closest('.avatar-btn'))
    document.querySelectorAll('.menu').forEach(m=>m.classList.remove('open'));
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){closeDrawer();document.querySelectorAll('.menu').forEach(m=>m.classList.remove('open'));}
});

// ── Session ──
async function loadMe(){
  me = await api('/api/me');
  if(!me.user) return;
  document.getElementById('hero-name').textContent = me.user.username;
  document.getElementById('user-avatar').src = me.user.avatar;
  document.getElementById('user-handle').textContent = me.user.handle ? '@'+me.user.handle : 'Signed in';
  renderGuild(me.guild);
}
function renderGuild(g){
  if(!g) return;
  document.getElementById('guild-name').textContent = g.name;
  const holder = document.getElementById('guild-icon');
  if(g.icon){
    const img = new Image(); img.src = g.icon; img.alt = '';
    holder.replaceWith(img); img.id = 'guild-icon';
  } else { holder.textContent = (g.name||'?').slice(0,1).toUpperCase(); }
}

// ── Navigation ──
function showSection(name, el){
  closeDrawer();
  document.querySelectorAll('.menu').forEach(m=>m.classList.remove('open'));
  document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));
  document.getElementById('sec-'+name).classList.add('active');
  const nav = el && el.classList.contains('nav-item') ? el : document.querySelector('.nav-item[data-sec="'+name+'"]');
  if(nav) nav.classList.add('active');
  window.scrollTo({top:0,behavior:'smooth'});
  if(name==='leaderboard') loadLeaderboard();
  if(name==='audit') loadAudit();
  if(name==='onleave') loadOnLeave();
  if(name==='memories') loadMemories();
  if(name==='events') loadEvents();
  if(name==='updates') loadUpdates();
  if(name==='ticketmods') loadTicketMods();
  if(name==='whitelist') loadWhitelist();
  if(name==='rolegrants') loadRoleGrants();
  if(name==='settings') loadSettings();
  if(name==='users') loadUsers();
  if(name==='overview'){loadStatus();loadChart();}
  if(name==='commands') loadCommands();
  if(name==='economy') loadEconomy();
  if(name==='activity') loadActivity();
}

// ── Status ──
async function loadStatus(){
  const d = await api('/api/status');
  if(!d || d.user_count===undefined) return;
  document.getElementById('bot-label').textContent = 'Bot online';
  document.getElementById('stat-users').textContent = d.user_count;
  document.getElementById('stat-vouches').textContent = d.total_vouches;
  document.getElementById('stat-memories').textContent = d.memory_count;
  document.getElementById('persona-badge').textContent = d.persona;
  const chatBadge = document.getElementById('chat-badge');
  chatBadge.textContent = d.chat_enabled ? 'Chat on' : 'Chat off';
  chatBadge.className = 'badge ' + (d.chat_enabled ? 'green' : 'red');
  loadOverview();
}

// ── Overview ──
async function loadOverview(){
  const d = await api('/api/leaderboard');
  lbData = d;
  ['pve','security','support'].forEach(cat=>{
    const catEl = document.getElementById('ov-' + (cat==='pve'?'host':cat));
    if(!catEl) return;
    const top3 = (d[cat]||[]).slice(0,3);
    catEl.innerHTML = '<div class="card-title" style="color:'+CAT_COLORS[cat]+'">'+CAT_NAMES[cat]+'</div>' +
      (top3.length ? top3.map((u,i)=>
        '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:13.5px">'+
        '<span style="color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">#'+(i+1)+' '+esc(u.resolved?u.name:u.uid)+'</span>'+
        '<span class="mono" style="color:var(--text)">'+fmt(u.points)+' pts</span></div>').join('')
        : '<div class="empty" style="padding:20px">Nothing here yet.</div>');
  });
}

// ── Leaderboard ──
async function loadLeaderboard(){
  if(!Object.keys(lbData).length) lbData = await api('/api/leaderboard');
  renderLbTable(currentLbCat);
}
function switchLbTab(cat, el){
  currentLbCat = cat;
  document.querySelectorAll('#sec-leaderboard .tabs .tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  const isGivers = cat === 'givers';
  document.getElementById('lb-giver-range').style.display = isGivers ? 'flex' : 'none';
  if(isGivers){ loadGiverBoard(); } else { renderLbTable(cat); }
}

let giverBoard = null;
async function loadGiverBoard(){
  const wrap = document.getElementById('lb-table-wrap');
  wrap.innerHTML = '<div class="empty">Loading…</div>';
  const days = document.getElementById('lb-days').value;
  const d = await api('/api/givers?days=' + days);
  giverBoard = d;
  if(!d || !d.givers || !d.givers.length){
    wrap.innerHTML = '<div class="empty">No Host vouches have been given in this window.</div>';
    return;
  }
  wrap.innerHTML =
    '<table><thead><tr><th>#</th><th>Voucher</th><th>Host vouches</th><th>Hosters</th>' +
    '<th>Points issued</th><th>Last</th></tr></thead><tbody>' +
    d.givers.map(function(g,i){
      const who = g.uid
        ? memberCell({uid:g.uid, name:g.name, avatar:g.avatar, resolved:g.resolved})
        : '<div class="member"><span class="ph">?</span><div class="who"><div class="nm">' +
          esc(g.name) + '</div><div class="id">no id</div></div></div>';
      return '<tr><td style="color:var(--dim)">' + (i+1) + '</td>' +
        '<td>' + who + '</td>' +
        '<td class="mono" style="color:var(--text);font-weight:600">' + fmt(g.given) + '</td>' +
        '<td class="mono">' + g.people + '</td>' +
        '<td class="mono">' + fmt(g.points) + '</td>' +
        '<td class="mono" style="font-size:11px;color:var(--muted)">' +
        String(g.last || '').substring(0,10) + '</td></tr>';
    }).join('') + '</tbody></table>';
}
function renderLbTable(cat){
  if(cat === 'givers'){ loadGiverBoard(); return; }
  const rows = (lbData[cat]||[]);
  const wrap = document.getElementById('lb-table-wrap');
  if(!rows.length){wrap.innerHTML='<div class="empty">No vouches recorded yet.</div>';return;}
  wrap.innerHTML = '<table><thead><tr><th>#</th><th>Member</th><th>Points</th><th>Vouches</th></tr></thead><tbody>' +
    rows.map((r,i)=>'<tr><td style="color:var(--dim)">'+(i+1)+'</td><td>'+memberCell(r)+'</td>'+
      '<td class="mono" style="color:var(--text);font-weight:600">'+fmt(r.points)+'</td>'+
      '<td style="color:var(--muted)">'+r.vouches+'</td></tr>').join('') + '</tbody></table>';
}

// ── Users ──
async function loadUsers(){
  const d = await api('/api/users');
  usersData = d;
  renderUsers(d);
  populateEvents();
}
function renderUsers(list){
  const tb = document.getElementById('users-table');
  if(!list.length){tb.innerHTML='<tr><td colspan="6" class="empty">No members found.</td></tr>';return;}
  tb.innerHTML = list.map(u=>'<tr>'+
    '<td>'+memberCell(u)+'</td>'+
    '<td class="mono">'+fmt(u.pve)+'</td>'+
    '<td class="mono">'+fmt(u.security)+'</td>'+
    '<td class="mono">'+fmt(u.support)+'</td>'+
    '<td class="mono" style="color:var(--text);font-weight:600">'+fmt(u.total)+'</td>'+
    '<td><button class="btn btn-ghost btn-sm" onclick="viewUser(\\''+u.uid+'\\')">View</button></td></tr>').join('');
}
function searchUsers(){
  const q = document.getElementById('user-search').value.toLowerCase().trim();
  renderUsers(q ? usersData.filter(u=>u.uid.includes(q) || (u.name||'').toLowerCase().includes(q)) : usersData);
}
async function viewUser(uid){
  currentDetailUid = uid;
  document.getElementById('user-detail-panel').style.display='block';
  currentDetailData = await api('/api/users/'+uid);
  document.getElementById('detail-name').innerHTML =
    (currentDetailData.resolved ? esc(currentDetailData.name) : 'Member') +
    ' <span class="mono" style="font-size:13px;color:var(--dim)">'+uid+'</span>';
  renderDetailCatTabs();
  renderDetailCat(currentDetailCat);
  document.getElementById('user-detail-panel').scrollIntoView({behavior:'smooth'});
}
function closeDetail(){
  document.getElementById('user-detail-panel').style.display='none';
  currentDetailUid=null;currentDetailData=null;
}
function renderDetailCatTabs(){
  document.getElementById('detail-cat-tabs').innerHTML = Object.keys(CAT_NAMES).map(cat=>
    '<div class="cat-tab '+(cat===currentDetailCat?'active':'')+'" onclick="switchDetailCat(\\''+cat+'\\',this)">'+CAT_NAMES[cat]+'</div>'
  ).join('');
}
function switchDetailCat(cat, el){
  currentDetailCat=cat;
  document.querySelectorAll('.cat-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  renderDetailCat(cat);
}
function renderDetailCat(cat){
  const rec = currentDetailData && currentDetailData.categories ? currentDetailData.categories[cat] : null;
  if(!rec){document.getElementById('detail-cat-content').innerHTML='<div class="empty">Nothing recorded here.</div>';return;}
  const evRows = Object.entries(rec.events||{}).filter(([,v])=>v>0)
    .map(([e,c])=>'<tr><td>'+esc(e)+'</td><td class="mono">'+c+'</td><td class="mono">'+fmt(c*(CATEGORY_EVENTS[cat][e]||0))+' pts</td></tr>').join('');
  const logRows = (rec.log||[]).slice().reverse().map(e=>'<tr>'+
    '<td class="mono" style="font-size:11px">'+(e.time||'').substring(0,16).replace('T',' ')+'</td>'+
    '<td>'+esc(e.event)+'</td><td class="mono">'+fmt(e.points)+'</td>'+
    '<td class="mono" style="font-size:11px">'+esc(e.by_name||e.by||'')+'</td>'+
    '<td><button class="btn btn-danger btn-sm" onclick="revertVouch(\\''+(e.idx_id||e.id)+'\\',\\''+cat+'\\')">Revert</button></td></tr>').join('');
  const rk = rec.rank;
  const rankBlock = rk ? '<div class="rank-row"><div class="rank-top">'+
      '<span class="rank-name">'+(rk.current?esc(rk.current):'No rank yet')+'</span>'+
      '<span class="rank-next">'+(rk.next?fmt(rk.remaining)+' to '+esc(rk.next):'Top rank reached')+'</span></div>'+
      '<div class="rank-bar"><div class="rank-fill" style="width:'+rk.pct+'%"></div></div></div>' : '';
  document.getElementById('detail-cat-content').innerHTML = rankBlock +
    '<div class="form-row" style="margin-bottom:16px">'+
      '<div class="stat"><div class="val" style="font-size:22px">'+fmt(rec.total_points)+'</div><div class="lbl">Points</div></div>'+
      '<div class="stat"><div class="val" style="font-size:22px">'+rec.total_vouches+'</div><div class="lbl">Vouches</div></div></div>'+
    (evRows?'<div class="table-wrap"><table style="margin-bottom:16px"><thead><tr><th>Event</th><th>Count</th><th>Points</th></tr></thead><tbody>'+evRows+'</tbody></table></div>':'')+
    (logRows?'<div class="card-title">Recent log</div><div class="table-wrap"><table><thead><tr><th>Time</th><th>Event</th><th>Pts</th><th>By</th><th></th></tr></thead><tbody>'+logRows+'</tbody></table></div>':'');
}
function populateEvents(){
  const cat = document.getElementById('add-cat').value;
  document.getElementById('add-event').innerHTML =
    Object.keys(CATEGORY_EVENTS[cat]).map(e=>'<option value="'+esc(e)+'">'+esc(e)+'</option>').join('');
}
async function submitAddVouch(){
  if(!currentDetailUid) return;
  const body = {uid:currentDetailUid,category:document.getElementById('add-cat').value,
    event_name:document.getElementById('add-event').value,count:parseInt(document.getElementById('add-count').value)||1};
  const r = await api('/api/vouches/add',{method:'POST',body:JSON.stringify(body)});
  const el = document.getElementById('add-result');
  if(r.ok){showAlert(el,'Added. New total: '+fmt(r.new_total)+' pts','success');viewUser(currentDetailUid);}
  else showAlert(el,r.error||'Could not add that vouch.','err');
}
async function revertVouch(logId,cat){
  if(!confirm('Revert this vouch?')) return;
  const r = await api('/api/vouches/revert',{method:'POST',body:JSON.stringify({uid:currentDetailUid,category:cat,log_id:logId})});
  if(r.ok) viewUser(currentDetailUid); else alert(r.error||'Could not revert that vouch.');
}

// ── Audit ──
function auditQuery(){
  const p = new URLSearchParams();
  const cat = document.getElementById('f-cat').value;
  const days = document.getElementById('f-days').value;
  const q = document.getElementById('f-q').value.trim();
  if(cat) p.set('category',cat);
  if(days && days!=='0') p.set('days',days);
  if(q) p.set('q',q);
  return p.toString();
}
let auditTimer = null;
function debouncedAudit(){clearTimeout(auditTimer);auditTimer=setTimeout(loadAudit,300);}
function clearAuditFilters(){
  document.getElementById('f-cat').value='';
  document.getElementById('f-days').value='0';
  document.getElementById('f-q').value='';
  loadAudit();
}
function exportAudit(){window.location.href='/api/auditlog.csv?'+auditQuery();}
async function loadAudit(){
  const data = await api('/api/auditlog?'+auditQuery());
  const el = document.getElementById('audit-list');
  if(!data.length){el.innerHTML='<div class="empty">Nothing matches those filters.</div>';return;}
  el.innerHTML = data.map(e=>'<div class="audit-item">'+
    '<div class="audit-dot" style="background:'+(CAT_COLORS[e.category]||'var(--dim)')+'"></div>'+
    '<div class="audit-content"><div class="main-text"><span style="color:'+CAT_COLORS[e.category]+'">'+
    (CAT_NAMES[e.category]||e.category)+'</span> - '+esc(e.event)+' <span class="mono">('+fmt(e.points)+' pts)</span>'+
    (e.backfilled?' <span style="font-size:10px;color:var(--amber)">[backfill]</span>':'')+'</div>'+
    '<div class="meta">to '+esc(e.name||e.uid)+' · by '+esc(e.by||'?')+' · '+(e.time||'').substring(0,16).replace('T',' ')+'</div>'+
    '</div></div>').join('');
}

// ── On Leave ──
function onLeaveActionText(e){
  if(e.action!=='start') return 'Returned from leave';
  let t = 'Reason: '+esc(e.reason||'-')+' · Duration: '+esc(e.duration||'-');
  if(e.note) t += ' · Note: '+esc(e.note);
  return t;
}
async function loadOnLeave(){
  const data = await api('/api/on_leave');
  const cur = document.getElementById('onleave-current');
  const hist = document.getElementById('onleave-history');
  const current = data.current||[];
  cur.innerHTML = current.length ? current.map(e=>
    '<div class="audit-item"><div class="audit-dot" style="background:var(--amber)"></div>'+
    '<div class="audit-content"><div class="main-text">'+esc(e.username||e.user_id)+'</div>'+
    '<div class="meta">'+onLeaveActionText(e)+' · since '+(e.time||'').substring(0,16).replace('T',' ')+'</div>'+
    '</div></div>').join('') : '<div class="empty">Nobody is on leave right now.</div>';
  const history = data.history||[];
  hist.innerHTML = history.length ? history.map(e=>
    '<div class="audit-item"><div class="audit-dot" style="background:'+(e.action==='start'?'var(--amber)':'var(--sage)')+'"></div>'+
    '<div class="audit-content"><div class="main-text">'+esc(e.username||e.user_id)+' - '+
    (e.action==='start'?'went on leave':'returned')+'</div>'+
    '<div class="meta">'+onLeaveActionText(e)+' · '+(e.time||'').substring(0,16).replace('T',' ')+'</div>'+
    '</div></div>').join('') : '<div class="empty">No on-leave activity yet.</div>';
}

// ── Memories ──
async function loadMemories(){
  const data = await api('/api/memories');
  const el = document.getElementById('memories-list');
  if(!data.length){el.innerHTML='<div class="empty">No memories saved yet.</div>';return;}
  el.innerHTML = data.map(m=>'<div class="memory-item"><div style="flex:1"><div class="text">'+esc(m.text)+
    '</div><div class="id">'+m.id+' · '+(m.time||'').substring(0,10)+'</div></div>'+
    '<button class="btn btn-danger btn-sm" onclick="deleteMemory(\\''+m.id+'\\')">Delete</button></div>').join('');
}
async function addMemory(){
  const text = document.getElementById('new-memory-text').value.trim();
  if(!text) return;
  const r = await api('/api/memories',{method:'POST',body:JSON.stringify({text})});
  showAlert(document.getElementById('memory-result'), r.ok?'Memory saved.':(r.error||'Could not save.'), r.ok?'success':'err');
  if(r.ok){document.getElementById('new-memory-text').value='';loadMemories();}
}
async function deleteMemory(id){
  if(!confirm('Delete this memory?')) return;
  await api('/api/memories/'+id,{method:'DELETE'});
  loadMemories();
}

// ── Events ──
async function loadEvents(){
  const data = await api('/api/events');
  document.getElementById('events-content').innerHTML = Object.entries(data).map(([event,times])=>
    '<div class="card" style="margin-bottom:14px"><div class="section-head" style="margin-bottom:10px">'+
    '<div class="card-title" style="margin:0">'+esc(event)+'</div>'+
    '<span class="mono">'+times.length+' times</span></div>'+
    '<div class="times-grid">'+times.map(t=>'<span class="time-chip">'+t+'</span>').join('')+'</div></div>').join('');
}

// ── Bot updates ──
function fmtUpdateTime(iso){
  return (iso||'').substring(0,16).replace('T',' ');
}
async function loadUpdates(){
  const data = await api('/api/updates');
  const el = document.getElementById('updates-list');
  if(!data.length){el.innerHTML='<div class="empty">No updates posted yet.</div>';return;}
  el.innerHTML = data.map(u=>
    '<div class="memory-item" style="align-items:flex-start;flex-direction:column;gap:8px">'+
      '<div style="width:100%;display:flex;justify-content:space-between;gap:12px;align-items:flex-start">'+
        '<div style="flex:1"><div class="text" style="white-space:pre-wrap">'+esc(u.content)+'</div>'+
        '<div class="id">Posted by '+esc(u.posted_by)+' \u00b7 '+fmtUpdateTime(u.posted_at)+
        (u.edited_at ? ' \u00b7 edited '+fmtUpdateTime(u.edited_at) : '')+'</div></div>'+
        '<button class="btn btn-ghost btn-sm" onclick="toggleEditUpdate(\\''+u.id+'\\')">Edit</button>'+
      '</div>'+
      '<div id="update-edit-'+u.id+'" style="display:none;width:100%">'+
        '<textarea id="update-edit-text-'+u.id+'" rows="4" style="width:100%">'+esc(u.content)+'</textarea>'+
        '<div style="margin-top:8px;display:flex;gap:8px">'+
          '<button class="btn btn-primary btn-sm" onclick="saveUpdate(\\''+u.id+'\\')">Save changes</button>'+
          '<button class="btn btn-ghost btn-sm" onclick="toggleEditUpdate(\\''+u.id+'\\')">Cancel</button>'+
        '</div>'+
        '<div id="update-edit-result-'+u.id+'"></div>'+
      '</div>'+
    '</div>'
  ).join('');
}
function toggleEditUpdate(id){
  const box = document.getElementById('update-edit-'+id);
  box.style.display = box.style.display === 'none' ? 'block' : 'none';
}
async function postUpdate(){
  const text = document.getElementById('new-update-text').value.trim();
  if(!text) return;
  const r = await api('/api/updates',{method:'POST',body:JSON.stringify({content:text})});
  showAlert(document.getElementById('update-post-result'), r.ok?'Posted to Discord.':(r.error||'Could not post.'), r.ok?'success':'err');
  if(r.ok){document.getElementById('new-update-text').value='';loadUpdates();}
}
async function saveUpdate(id){
  const text = document.getElementById('update-edit-text-'+id).value.trim();
  if(!text) return;
  const r = await api('/api/updates/'+id,{method:'POST',body:JSON.stringify({content:text})});
  showAlert(document.getElementById('update-edit-result-'+id), r.ok?'Message updated on Discord.':(r.error||'Could not save.'), r.ok?'success':'err');
  if(r.ok) loadUpdates();
}

// ── Ticket mods ──
async function loadTicketMods(){
  const data = await api('/api/ticket_mods');
  const el = document.getElementById('ticketmods-list');
  if(!data.length){el.innerHTML='<div class="empty">No ticket mod roles added yet.</div>';return;}
  el.innerHTML = data.map(m=>'<div class="memory-item"><div style="flex:1"><div class="text">'+esc(m.name)+
    '</div></div><button class="btn btn-danger btn-sm" onclick="deleteTicketMod(\\''+m.id+'\\')">Remove</button></div>').join('');
}
async function addTicketMod(){
  const name = document.getElementById('new-ticketmod-name').value.trim();
  if(!name) return;
  const r = await api('/api/ticket_mods',{method:'POST',body:JSON.stringify({name})});
  showAlert(document.getElementById('ticketmod-result'), r.ok?'Role added.':(r.error||'Could not add.'), r.ok?'success':'err');
  if(r.ok){document.getElementById('new-ticketmod-name').value='';loadTicketMods();}
}
async function deleteTicketMod(id){
  if(!confirm('Remove this role from ticket mods?')) return;
  await api('/api/ticket_mods/'+id,{method:'DELETE'});
  loadTicketMods();
}

// ── Anti-nuke whitelist ──
async function loadWhitelist(){
  const data = await api('/api/antinuke_whitelist');
  const el = document.getElementById('whitelist-list');
  if(!data.length){el.innerHTML='<div class="empty">Nobody whitelisted yet.</div>';return;}
  el.innerHTML = data.map(w=>'<div class="memory-item"><div style="flex:1"><div class="text">'+esc(w.name)+
    '</div><div class="id">'+esc(w.id)+'</div></div>'+
    '<button class="btn btn-danger btn-sm" onclick="deleteWhitelist(\\''+w.id+'\\')">Remove</button></div>').join('');
}
async function addWhitelist(){
  const id = document.getElementById('new-whitelist-id').value.trim();
  const name = document.getElementById('new-whitelist-name').value.trim();
  if(!id) return;
  const r = await api('/api/antinuke_whitelist',{method:'POST',body:JSON.stringify({id,name})});
  showAlert(document.getElementById('whitelist-result'), r.ok?'Added to whitelist.':(r.error||'Could not add.'), r.ok?'success':'err');
  if(r.ok){document.getElementById('new-whitelist-id').value='';document.getElementById('new-whitelist-name').value='';loadWhitelist();}
}
async function deleteWhitelist(id){
  if(!confirm('Remove this user from the anti-nuke whitelist?')) return;
  await api('/api/antinuke_whitelist/'+id,{method:'DELETE'});
  loadWhitelist();
}

// ── Role grants ──
async function loadRoleGrants(){
  const data = await api('/api/role_grants');
  const el = document.getElementById('rolegrant-list');
  if(!data.length){el.innerHTML='<div class="empty">No role grants yet.</div>';return;}
  el.innerHTML = data.map(function(g){
    return '<div class="memory-item"><div style="flex:1"><div class="text"><b>'+esc(g.granter_role_name)+
      '</b> <span class="mono" style="color:var(--muted)">can grant</span> <b>'+esc(g.role_name)+'</b></div></div>'+
      '<button class="btn btn-danger btn-sm" onclick="deleteRoleGrant(\\''+g.id+'\\')">Remove</button></div>';
  }).join('');
}
async function addRoleGrant(){
  const granter_role_name = document.getElementById('new-rolegrant-granter').value.trim();
  const role_name = document.getElementById('new-rolegrant-role').value.trim();
  if(!granter_role_name || !role_name) return;
  const r = await api('/api/role_grants',{method:'POST',body:JSON.stringify({granter_role_name,role_name})});
  showAlert(document.getElementById('rolegrant-result'), r.ok?'Role grant added.':(r.error||'Could not add.'), r.ok?'success':'err');
  if(r.ok){
    document.getElementById('new-rolegrant-granter').value='';
    document.getElementById('new-rolegrant-role').value='';
    loadRoleGrants();
  }
}
async function deleteRoleGrant(id){
  if(!confirm('Remove this role grant?')) return;
  await api('/api/role_grants/'+id,{method:'DELETE'});
  loadRoleGrants();
}

// ── Site activity ──
async function loadActivity(){
  const days = document.getElementById('act-days').value;
  const d = await api('/api/analytics?days=' + days);
  if(!d || !d.labels) return;

  const t = d.totals || {};
  document.getElementById('act-stats').innerHTML =
    '<div class="stat"><div class="val">' + fmt(t.views || 0) + '</div><div class="lbl">Page views</div></div>' +
    '<div class="stat"><div class="val">' + (t.people || 0) + '</div><div class="lbl">People who visited</div></div>' +
    '<div class="stat"><div class="val">' + fmt(t.per_day || 0) + '</div><div class="lbl">Views per day</div></div>' +
    '<div class="stat"><div class="val" style="font-size:18px">' + (t.busiest || '-') +
      '</div><div class="lbl">Busiest day</div></div>';

  drawActivityChart(d);

  const el = document.getElementById('act-people');
  if(!d.people.length){
    el.innerHTML = '<div class="empty">Nobody has opened the site in this window.</div>';
    return;
  }
  el.innerHTML = '<table><thead><tr><th>Member</th><th>Views</th><th>Days active</th><th>Last seen</th></tr></thead><tbody>' +
    d.people.map(function(p){
      return '<tr><td>' + memberCell(p) + '</td>' +
        '<td class="mono">' + p.views + '</td>' +
        '<td class="mono">' + p.days + '</td>' +
        '<td class="mono" style="font-size:11px;color:var(--muted)">' +
        String(p.last_seen || '').substring(0,16).replace('T',' ') + '</td></tr>';
    }).join('') + '</tbody></table>';
}

function drawActivityChart(d){
  const holder = document.getElementById('act-chart');
  const max = Math.max(1, Math.max.apply(null, d.views.concat(d.uniques)));
  if(!d.views.some(function(v){ return v > 0; })){
    holder.innerHTML = '<div class="empty">No visits recorded yet.</div>';
    document.getElementById('act-legend').innerHTML = '';
    return;
  }
  const W = 760, H = 240, PL = 44, PR = 12, PT = 14, PB = 28;
  const n = d.labels.length;
  const x = function(i){ return PL + (i * (W - PL - PR)) / Math.max(1, n - 1); };
  const y = function(v){ return PT + (H - PT - PB) * (1 - v / max); };
  let g = '';
  for(let i = 0; i <= 4; i++){
    const v = max * i / 4, yy = y(v);
    g += '<line x1="' + PL + '" y1="' + yy + '" x2="' + (W - PR) + '" y2="' + yy +
         '" stroke="#2a2432" stroke-width="1"/>' +
         '<text x="' + (PL - 8) + '" y="' + (yy + 4) + '" fill="#6b5f78" font-size="11" text-anchor="end">' +
         Math.round(v) + '</text>';
  }
  const step = Math.max(1, Math.floor(n / 5));
  for(let i = 0; i < n; i += step){
    g += '<text x="' + x(i) + '" y="' + (H - 8) + '" fill="#6b5f78" font-size="11" text-anchor="middle">' +
         d.labels[i].slice(5) + '</text>';
  }
  const line = function(vals, color, dash){
    return '<polyline points="' + vals.map(function(v,i){ return x(i) + ',' + y(v); }).join(' ') +
      '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"' +
      (dash ? ' stroke-dasharray="4 4"' : '') + '/>';
  };
  holder.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" role="img">' +
    g + line(d.views, '#7fc2b8', false) + line(d.uniques, '#9c8fe0', true) + '</svg>';
  const pages = d.pages || {};
  document.getElementById('act-legend').innerHTML =
    '<span><i style="background:#7fc2b8"></i>Page views</span>' +
    '<span><i style="background:#9c8fe0"></i>Unique visitors</span>' +
    '<span style="color:var(--dim)">dashboard ' + (pages.dashboard || 0) +
    ' / profile ' + (pages.profile || 0) + '</span>';
}

// ── Points and ranks ──
let ECONOMY = null;
let ecoCat = 'pve';

function ecoRow(name, value, numMin, cooldownMin){
  const row = document.createElement('div');
  row.className = 'eco-row';
  const a = document.createElement('input');
  a.className = 'nm'; a.value = name == null ? '' : name; a.placeholder = 'Name';
  const b = document.createElement('input');
  b.className = 'num'; b.type = 'number'; b.step = '0.5'; b.min = String(numMin);
  b.value = value == null ? '' : value;
  row.appendChild(a); row.appendChild(b);
  if(cooldownMin !== undefined){
    const c = document.createElement('input');
    c.className = 'num cd'; c.type = 'number'; c.step = '1'; c.min = '0';
    c.title = 'Cooldown in minutes, 0 = none';
    c.value = cooldownMin == null ? 0 : cooldownMin;
    row.appendChild(c);
  }
  const x = document.createElement('button');
  x.className = 'del'; x.type = 'button'; x.title = 'Remove'; x.textContent = '\u00d7';
  x.onclick = function(){ row.remove(); };
  row.appendChild(x);
  return row;
}
function readRows(id, valueKey, extraKey){
  const out = [];
  document.getElementById(id).querySelectorAll('.eco-row').forEach(function(r){
    const name = r.querySelector('.nm').value.trim();
    const num = r.querySelector('.num').value;
    if(!name && num === '') return;
    const item = {name: name};
    item[valueKey] = num === '' ? 0 : Number(num);
    if(extraKey){
      const cd = r.querySelector('.cd');
      item[extraKey] = cd && cd.value !== '' ? Number(cd.value) : 0;
    }
    out.push(item);
  });
  return out;
}
async function loadEconomy(){
  ECONOMY = await api('/api/economy');
  if(!ECONOMY || !ECONOMY.events) return;
  CATEGORY_EVENTS = ECONOMY.events;
  renderEconomy();
}
function renderEconomy(){
  if(!ECONOMY) return;
  const events = ECONOMY.events[ecoCat] || {};
  const ranks = ECONOMY.ranks[ecoCat] || [];
  const metric = (ECONOMY.metric || {})[ecoCat] === 'vouches' ? 'vouches' : 'points';

  const cooldowns = (ECONOMY.cooldowns || {})[ecoCat] || {};
  const ev = document.getElementById('ev-rows');
  ev.innerHTML = '';
  Object.keys(events).forEach(function(name){
    const cdMin = Math.round((cooldowns[name] || 0) / 60);
    ev.appendChild(ecoRow(name, events[name], 0, cdMin));
  });

  const rk = document.getElementById('rk-rows');
  rk.innerHTML = '';
  ranks.forEach(function(r){ rk.appendChild(ecoRow(r[1], r[0], 0)); });

  document.getElementById('rk-unit').textContent = 'Unlocks at (' + metric + ')';
  document.getElementById('rk-note').textContent =
    'Measured in ' + metric + '. Role names must match your Discord roles exactly.';
  if(!ranks.length) rk.innerHTML = '<div class="empty">No rank ladder for this category yet.</div>';
}
async function saveEconomy(section){
  const el = document.getElementById(section === 'events' ? 'ev-result' : 'rk-result');
  const body = {section: section, category: ecoCat};
  if(section === 'events') body.events = readRows('ev-rows', 'points', 'cooldown');
  else body.ranks = readRows('rk-rows', 'at');
  const r = await api('/api/economy', {method:'POST', body: JSON.stringify(body)});
  if(!r.ok){ showAlert(el, r.error || 'Could not save.', 'err'); return; }
  if(section === 'events'){
    let msg = 'Saved ' + r.count + ' events. New vouches use these values right away.';
    if(r.removed && r.removed.length){
      msg += ' Removed: ' + r.removed.map(esc).join(', ') + '. Past vouches keep their original points.';
    }
    showAlert(el, msg, 'success');
  } else {
    showAlert(el, 'Saved ' + r.count + ' ranks. Run a resync in Settings to apply them to everyone now.', 'success');
  }
  await loadEconomy();
}
async function resetEconomy(section){
  if(!confirm('Reset this section back to the values in the bot code?')) return;
  await api('/api/economy/reset', {method:'POST', body: JSON.stringify({section: section, category: ecoCat})});
  await loadEconomy();
}
document.addEventListener('DOMContentLoaded', function(){
  document.getElementById('eco-tabs').addEventListener('click', function(e){
    const tab = e.target.closest('[data-eco]');
    if(!tab) return;
    ecoCat = tab.dataset.eco;
    document.querySelectorAll('#eco-tabs .tab').forEach(function(t){ t.classList.remove('active'); });
    tab.classList.add('active');
    renderEconomy();
  });
  document.getElementById('ev-add').onclick = function(){
    document.getElementById('ev-rows').appendChild(ecoRow('', '', 0, 0));
  };
  document.getElementById('rk-add').onclick = function(){
    const rk = document.getElementById('rk-rows');
    if(rk.querySelector('.empty')) rk.innerHTML = '';
    rk.appendChild(ecoRow('', '', 0));
  };
  document.getElementById('ev-save').onclick = function(){ saveEconomy('events'); };
  document.getElementById('rk-save').onclick = function(){ saveEconomy('ranks'); };
  document.getElementById('ev-reset').onclick = function(){ resetEconomy('events'); };
  document.getElementById('rk-reset').onclick = function(){ resetEconomy('ranks'); };
});

// ── Chart ──
async function loadChart(){
  const days = document.getElementById('chart-days').value;
  const d = await api('/api/points_over_time?days='+days);
  if(!d || !d.labels) return;
  renderChart(d);
}
function renderChart(d){
  const W=760,H=240,PL=44,PR=12,PT=14,PB=28;
  const cats=['pve','security','support'];
  const colors={pve:'#7fc2b8',security:'#9c8fe0',support:'#5fcf9f'};
  const all=cats.flatMap(c=>d.series[c]||[]);
  const max=Math.max(1,...all);
  const n=d.labels.length;
  const x=i=>PL+(i*(W-PL-PR))/Math.max(1,n-1);
  const y=v=>PT+(H-PT-PB)*(1-v/max);
  let g='';
  for(let i=0;i<=4;i++){
    const v=max*i/4, yy=y(v);
    g+='<line x1="'+PL+'" y1="'+yy+'" x2="'+(W-PR)+'" y2="'+yy+'" stroke="#2a2432" stroke-width="1"/>'+
       '<text x="'+(PL-8)+'" y="'+(yy+4)+'" fill="#6b5f78" font-size="11" text-anchor="end">'+fmt(Math.round(v))+'</text>';
  }
  const step=Math.max(1,Math.floor(n/5));
  for(let i=0;i<n;i+=step){
    g+='<text x="'+x(i)+'" y="'+(H-8)+'" fill="#6b5f78" font-size="11" text-anchor="middle">'+d.labels[i].slice(5)+'</text>';
  }
  let lines='';
  cats.forEach(c=>{
    const pts=(d.series[c]||[]).map((v,i)=>x(i)+','+y(v)).join(' ');
    lines+='<polyline points="'+pts+'" fill="none" stroke="'+colors[c]+'" stroke-width="2" '+
           'stroke-linejoin="round" stroke-linecap="round"/>';
  });
  document.getElementById('chart').innerHTML =
    '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet" role="img">'+g+lines+'</svg>';
  document.getElementById('chart-legend').innerHTML = cats.map(c=>
    '<span><i style="background:'+colors[c]+'"></i>'+CAT_NAMES[c]+' - '+fmt(d.totals[c])+' pts</span>').join('');
}

// ── Role resync ──
async function resyncRoles(){
  const btn=document.getElementById('resync-btn'), el=document.getElementById('resync-result');
  btn.disabled=true; btn.textContent='Resyncing…';
  const r=await api('/api/roles/resync',{method:'POST'});
  btn.disabled=false; btn.textContent='Resync all roles';
  if(r.ok) showAlert(el,'Done - '+(r.updated||0)+' member(s) updated, '+(r.checked||0)+' checked.','success');
  else showAlert(el, r.error||'Resync failed.','err');
}

// ── Custom commands ──
let editingCommand = null;
let commandsCache = [];
async function loadCommands(){
  const list = await api('/api/commands');
  commandsCache = Array.isArray(list) ? list : [];
  const el = document.getElementById('cmd-list');
  if(!commandsCache.length){el.innerHTML='<div class="empty">No custom commands yet. Make your first one above.</div>';return;}
  el.innerHTML = commandsCache.map((c,i)=>'<div class="cmd-item '+(c.enabled?'':'off')+'">'+
    '<div class="body"><div class="nm">?'+esc(c.name)+'</div>'+
    '<div class="rp">'+esc(c.response)+'</div>'+
    '<div class="mt">'+(c.embed?'embed · ':'')+(c.uses||0)+' uses · by '+esc(c.created_by||'?')+'</div></div>'+
    '<button class="btn btn-ghost btn-sm" data-edit="'+i+'">Edit</button>'+
    '<button class="btn btn-danger btn-sm" data-del="'+i+'">Delete</button></div>').join('');
  el.querySelectorAll('[data-edit]').forEach(b=>{
    b.onclick=()=>editCommand(commandsCache[Number(b.dataset.edit)]);
  });
  el.querySelectorAll('[data-del]').forEach(b=>{
    b.onclick=()=>deleteCommand(commandsCache[Number(b.dataset.del)].name);
  });
}
function editCommand(c){
  if(!c) return;
  editingCommand = c.name;
  document.getElementById('cmd-form-title').textContent = 'Editing ?'+c.name;
  document.getElementById('cmd-name').value = c.name;
  document.getElementById('cmd-title').value = c.title||'';
  document.getElementById('cmd-response').value = c.response||'';
  document.getElementById('cmd-embed').checked = !!c.embed;
  document.getElementById('cmd-color').value = c.color||'#7fc2b8';
  window.scrollTo({top:0,behavior:'smooth'});
}
function resetCommandForm(){
  editingCommand = null;
  document.getElementById('cmd-form-title').textContent = 'Create a command';
  ['cmd-name','cmd-title','cmd-response'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('cmd-embed').checked=false;
  document.getElementById('cmd-color').value='#7fc2b8';
}
async function saveCommand(){
  const body={
    name:document.getElementById('cmd-name').value,
    title:document.getElementById('cmd-title').value,
    response:document.getElementById('cmd-response').value,
    embed:document.getElementById('cmd-embed').checked,
    color:document.getElementById('cmd-color').value,
    enabled:true,
  };
  const r=await api('/api/commands',{method:'POST',body:JSON.stringify(body)});
  const el=document.getElementById('cmd-result');
  if(r.ok){showAlert(el,'Saved. Members can use ?'+r.command.name+' right away.','success');resetCommandForm();loadCommands();}
  else showAlert(el, r.error||'Could not save that command.','err');
}
async function deleteCommand(name){
  if(!confirm('Delete ?'+name+'?')) return;
  await api('/api/commands/'+encodeURIComponent(name),{method:'DELETE'});
  loadCommands();
}

// ── Settings ──
async function loadSettings(){
  const d = await api('/api/settings');
  document.getElementById('chat-toggle').checked = d.chat_enabled;
  document.getElementById('chat-toggle-label').textContent = d.chat_enabled ? 'Chat is on' : 'Chat is off';
  document.getElementById('persona-select').value = d.persona;
  const c = d.config||{};
  document.getElementById('cfg-pve').value = c.pve_channel_id||'';
  document.getElementById('cfg-security').value = c.security_channel_id||'';
  document.getElementById('cfg-support').value = c.support_channel_id||'';
  document.getElementById('cfg-lb').value = c.live_leaderboard_channel_id||'';
  document.getElementById('cfg-audit').value = c.audit_log_channel_id||'';
  document.getElementById('cfg-events').value = c.event_ping_channel_id||'';
  document.getElementById('cfg-chime').value = c.chime_in_channel_id||'';
  document.getElementById('cfg-leave-btn').value = c.on_leave_button_channel_id||'';
  document.getElementById('cfg-leave-log').value = c.on_leave_log_channel_id||'';
}
async function toggleChat(){
  const enabled = document.getElementById('chat-toggle').checked;
  await api('/api/settings',{method:'POST',body:JSON.stringify({chat_enabled:enabled})});
  document.getElementById('chat-toggle-label').textContent = enabled ? 'Chat is on' : 'Chat is off';
  const chatBadge = document.getElementById('chat-badge');
  chatBadge.textContent = enabled ? 'Chat on' : 'Chat off';
  chatBadge.className = 'badge ' + (enabled ? 'green' : 'red');
}
async function savePersona(){
  const p = document.getElementById('persona-select').value;
  await api('/api/settings',{method:'POST',body:JSON.stringify({persona:p})});
  document.getElementById('persona-badge').textContent = p;
}
async function saveSettings(){
  const body = {
    pve_channel_id: document.getElementById('cfg-pve').value,
    security_channel_id: document.getElementById('cfg-security').value,
    support_channel_id: document.getElementById('cfg-support').value,
    live_leaderboard_channel_id: document.getElementById('cfg-lb').value,
    audit_log_channel_id: document.getElementById('cfg-audit').value,
    event_ping_channel_id: document.getElementById('cfg-events').value,
    chime_in_channel_id: document.getElementById('cfg-chime').value,
    on_leave_button_channel_id: document.getElementById('cfg-leave-btn').value,
    on_leave_log_channel_id: document.getElementById('cfg-leave-log').value,
    persona: document.getElementById('persona-select').value,
    chat_enabled: document.getElementById('chat-toggle').checked,
  };
  const r = await api('/api/settings',{method:'POST',body:JSON.stringify(body)});
  showAlert(document.getElementById('settings-result'),
    r.ok ? 'Settings saved. Restart the bot to apply channel changes.' : 'Could not save settings.',
    r.ok ? 'success' : 'err');
}

// ── Init ──
loadMe();
loadStatus();
loadEconomy();
setInterval(loadStatus, 30000);
</script>
</body>
</html>""".replace("__LOGO__", LOGO_SRC)

# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

def run_dashboard():
    port = int(os.environ.get("PORT", 8080))
    print(f"[Dashboard] Starting on http://0.0.0.0:{port}")
    if not oauth_configured():
        print("[Dashboard] Discord login is NOT configured - set DISCORD_CLIENT_ID, "
              "DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI.")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_dashboard()
