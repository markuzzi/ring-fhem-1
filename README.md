# ring-fhem
Python-based ring connector for FHEM.

Zur installation müssen zwei Python3.7 libs installiert werden:

    pip3.7 install git+https://github.com/tchellomello/python-ring-doorbell
    pip3.7 install fhem

Dann die zwei Dateien ring.py und run_ring runterladen und z.B. in /opt/fhem/bin ablegen.
In der ring.py muss noch der User und das Passwort des Ring Accounts eingetragen werden. Hier tuts auch ein Gast Account.
Alternativ kann können User und Passwort über Parameter übergeben werden: `python3 ring.py --help`

Die run_ring sorgt für die Ausführung der ring.py als user "fhem" und wird bei mir via crontab regelmäßig angetriggert (sollte mal ein Fehler unterlaufen):

    @reboot /opt/fhem/bin/run_ring
    @hourly /opt/fhem/bin/run_ring

Eine Alternative mit FHEM als Job Scheduler ist unten beschrieben.

Wenn noch kein token gespeichert wurde, wird beim Starten ein Benutzername/Passwort abgefragt, so wie der 2FA-Code welchen Ring an den Acount schickt. Nachdem dieser eingeben wurde wird ein AuthToken in einer Datei gesichertm so dass folgende Starts der ring.py ohne Interaktion funktionieren, in dem einfach das Token aus dem Cache gelesen und präsentiert wird.

In fhem habe ich einen Dummy angelegt mit dem Namen "Ring_[RingDeviceName]" (Achtung, wenn der Name nicht passt, muss die ring.py angepasst werden). [RingDeviceName] wird durch den Namen des Ring Devices ersetzt, wobei Leerzeichen entfernt werden. Bsp: Ring Device heißt "Front Door", in FHEM wird "Ring_FrontDoor" geschrieben. Der entsprechende Dummy wird wie folgt angelegt:

    define Ring_FrontDoor dummy
    attr Ring_FrontDoor setList none motion ring
    attr Ring_FrontDoor devStateIcon none:it_camera@green motion:secur_alarm@red ring:secur_alarm@orange

Ein DOIF sorgt dafür, dass der Status nach 5sec zurück gesetzt wird und eine Aktion ausgeführt wird. Beispiel wie folgt, FK_Haustuer ist ein Fenster/Türkontakt xmp3 eine Klingel:

    defmod Ring_FrontDoor_DOIF DOIF ([Ring_FrontDoor] eq "ring" and [FK_Haustuer] eq "closed" and [FK_Haustuer:state:sec] > 5)
    	(set xmp3 playTone 0) (set Ring_FrontDoor none)
    DOELSEIF ([Ring_FrontDoor] eq "motion" and [FK_Haustuer] eq "closed" and [FK_Haustuer:state:sec] > 2)
    	(set xmp3 playTone 48) (set Ring_FrontDoor none)
    DOELSE
    	(set Ring_FrontDoor none)  
    attr Ring_FrontDoor_DOIF cmdState ring,none|motion,none|none
    attr Ring_FrontDoor_DOIF do always
    attr Ring_FrontDoor_DOIF event-on-change-reading .*
    attr Ring_FrontDoor_DOIF stateFormat wait_timer
    attr Ring_FrontDoor_DOIF wait 0,5:0,5:0
    
## FHEM als JOB Scheduler
Um FHEM zum Start der ring.py zu nutzen, kann folgendes DOIF verwendet werden:

    defmod DOIF.Job.Ring DOIF init {\
      use POSIX qw(strftime);;\
    \
      $_cmd = AttrVal("$SELF","command","");;\
      $_log_template = AttrVal("$SELF","log","./log/$SELF_%Y-%m-%d.log");;\
    \
      $_pid=0;;\
      $_tries=0;;\
      $_reset=0;;\
    \
      set_Reading("command",$_cmd,0);;\
      set_Reading("log_template",$_log_template,0);;\
      set_Reading("PID","none",0);;\
      set_Reading("tries",0,0);;\
      set_State("Initialized");;\
    }\
    \
    subs {\
      sub run() {\
        $_log=strftime($_log_template, localtime);;\
        my $c = "$_cmd >>$_log 2>&1 &";;\
        set_Reading("completecmd", $c, 0);;\
        system($c);;\
        set_State("Process started");;\
      }\
      sub reset_job() {\
        use POSIX qw(strftime);;\
        $_log=strftime($_log_template, localtime);;\
        $_reset=1;;\
        set_State("Resetting job...");;\
      }\
    }\
    \
    {\
      if([+00:00:05]) {\
        set_State("Checking...");;\
    \
        $_pid = `pgrep -x -d, -f "$_cmd"`;;\
        set_Reading("PID", $_pid,0);;\
    \
        if(length($_pid) > 0) {\
          $_tries=0;;\
    \
          my @pids=split(/,/,$_pid);;\
          my $cnt=0;;\
          fhem("deletereading $SELF proc_.*", 1);;\
          set_Reading_Begin();;\
          foreach (@pids) {\
            if($_reset) {\
              kill 9, $_;;\
              set_Reading_Update("proc_$_","killed");;\
            } else {\
              if(kill 0, $_) {\
                $cnt++;;\
                set_Reading_Update("proc_$_","running");;\
              } else {\
                set_Reading_Update("proc_$_","not responding");;\
                kill 9, $_;;\
                set_Reading_Update("proc_$_","killed");;\
              }\
            }\
          }\
          \
          $_reset=0 if($_reset);;\
          \
          set_Reading_End(0);;\
          set_State("$cnt/" . scalar(@pids) . " processes running");;\
    \
        } else {\
          set_Reading("tries", $_tries++);;\
          if($_tries > 10) {\
              ::sendMessage("Job", "Aborting " . $_cmd . " after 10 tries.", "Markus") if($_tries == 10);;\
              set_State("Aborting after 10 tries");;\
              run() if($_tries % 100 == 0);;\
          } else {\
              run();;\
          }\
        }\
      }\
    \
      if([$SELF:reset:sec] < 5) {\
        $_tries=0;;\
        reset_job();;\
      }\
      \
      if([00:01]) {\
        reset_job();;\
      }\
    }
    attr DOIF.Job.Ring userattr command log
    attr DOIF.Job.Ring command python3 ./FHEM/ring.py
    attr DOIF.Job.Ring icon edit_settings
    attr DOIF.Job.Ring log ./log/Ring_%Y-%m-%d.log
    attr DOIF.Job.Ring readingList reset
    attr DOIF.Job.Ring room System->Jobs
    attr DOIF.Job.Ring setList reset
    attr DOIF.Job.Ring webCmd reset:disable:enable

Viel Erfolg!
