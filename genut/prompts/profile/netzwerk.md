**Netzwerk (Subnetting, Protokolle, Konfiguration)**
- Subnetting-Aufgaben bekommen einen `check` mit `art: "subnetz"`: `netz` = Adresse mit Präfix laut Angabe (z. B. `192.168.10.77/26`), `erwartet` = nur die gefragten Werte (`netzadresse`, `broadcast`, `erster_host`, `letzter_host`, `hosts` = nutzbare Hosts, `maske`, `praefix`). IPv6 ebenso (ohne `broadcast`/`maske`).
- Setze in jedes Thema über IP-Adressen/Subnetting einen `subnetzrechner`-Block (`start` z. B. `192.168.1.10/24`), damit der Schüler selbst rechnen kann.
- Befehle (Cisco IOS, Linux, Windows) als `befehl`-Block mit `kontext` (z. B. `Router(config)#`, `bash`) und kurzer Erklärung. Längere Konfigurationen als `code`-Block.
- Topologien und Abläufe (z. B. TCP-Handshake, DHCP) als `diagramm`-Block (Mermaid `flowchart` bzw. `sequenceDiagram`).
- OSI/TCP-IP-Schichten, Ports, Protokolle: gern als `tabelle`.
- Rechnungen (z. B. Übertragungszeit) mit `check` `numerisch`.
