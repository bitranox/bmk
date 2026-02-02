we want to provode following cli commands :

t / test       --> test.sh  ---> pass the actual directory.
ti / testi / testintegration  --> test_integration_???_<commment>.sh
c / commit  --> commit.sh


create a new command, same pattern as our other commands, command : bump bmp b , subcommands ma/major m/minor p/patch --> bump_major_010_bump.sh, bump_minor_010.sh, bump_patch_010.sh
create a small standalon python script who does the heavvy lifting and is called by that shellscripts: 
- increment major/minor/patch in pyproj.toml
- rename the top [unreleased] section in changelog to the new version number, and put date and time local like : 
"[1.0.1] yyyy-mm-dd hh:mm:ss"  localtime
- if there is no [unreleased] section in changelog just create the new entry
- after that, create a new [unreleased] section above that 

create a new command, same pattern as our other commands, command : dependencies deps d , optional subcommands u,update, optional -u/--update  --> dependencies_010_dependencies.sh, dependencies_update_010_dependencies_update.sh
use a small standalon python script who does the heavvy lifting and is called by that shellscripts: 
adopt _dependencies.py and refractor it to your needs
d / deps / dependencies --update
du / depsupdate / dependencies_update


create a new command, same pattern as our other commands, command : clean, cln, cl  --> clean_010_clean.sh
use a small standalon python script who does the heavvy lifting and is called by that shellscripts: 
adopt _clean.py and refractor it to your needs


p / push --> push.sh
r / run --> run.sh
 


rel / release

bld / build

h/help/hlp / --help

m / mnu / menue


