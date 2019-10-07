# Indiana Jones and The Infernal machine Add-on for Blender 2.79
The add-on provides import/export scripts for game resources e.g. models (.3do) and animations (.key).  
In addition, it can also import game materials (.mat).


<img src="https://github.com/smlu/blender-ijim/blob/master/demo/inmcar.png" width="80%"/>
<img src="https://github.com/smlu/blender-ijim/blob/master/demo/in_jump_fwd.gif" width="80%"/>

## Requirements
Blender 2.79, you can download it [here](https://download.blender.org/release/Blender2.79/latest/).  
To import game resources into blender they need to be extracted from `*.GOB` and `*.CND` files first. Use `gobext` and `cndtool` from [this](https://github.com/smlu/ProjectMarduk) repo.

## Installation
   1. Download `ijim.zip` file from the [Releases](https://github.com/smlu/blender-ijim/releases) page.
   2. Open Blender and select `File > User Preferences > Add-ons > Install Add-on from File`   
   and select the downloaded `ijim.zip` file.
   3. Enable the add-on by clicking the checkbox next to the add-on name.
   4. Select `Save User Settings` in the lower left and close the window.
   
## Usage
### File naming convention
The maximum file name length, including the file extension in Jones3d engine is limited to 64 characters.  
Therefore all longer file names have to be abbreviated.  
Some of general abbreviations:  
   &nbsp;&nbsp;&nbsp;&nbsp; **dflt** - default  
   &nbsp;&nbsp;&nbsp;&nbsp; **bk**   - back  
   &nbsp;&nbsp;&nbsp;&nbsp; **by**   - boy  
   &nbsp;&nbsp;&nbsp;&nbsp; **com**  - commy    
   &nbsp;&nbsp;&nbsp;&nbsp; **fr**   - front    
   &nbsp;&nbsp;&nbsp;&nbsp; **ib**   - ice boss   
   &nbsp;&nbsp;&nbsp;&nbsp; **ij**   - indy jeep  
   &nbsp;&nbsp;&nbsp;&nbsp; **in**   - indy  
   &nbsp;&nbsp;&nbsp;&nbsp; **inv**  - inventory  
   &nbsp;&nbsp;&nbsp;&nbsp; **ir**   - indy raft  
   &nbsp;&nbsp;&nbsp;&nbsp; **lb**   - lava boss  
   &nbsp;&nbsp;&nbsp;&nbsp; **mc**   - mine car  
   &nbsp;&nbsp;&nbsp;&nbsp; **mo**   - monkey  
   &nbsp;&nbsp;&nbsp;&nbsp; **by**   - boy  
   &nbsp;&nbsp;&nbsp;&nbsp; **ol**   - old lady  
   &nbsp;&nbsp;&nbsp;&nbsp; **rft**  - raft  
   &nbsp;&nbsp;&nbsp;&nbsp; **sn**   - snake  
   &nbsp;&nbsp;&nbsp;&nbsp; **sp**   - spider  
   &nbsp;&nbsp;&nbsp;&nbsp; **so**   - sophia  
   &nbsp;&nbsp;&nbsp;&nbsp; **tu**   - turner  
   &nbsp;&nbsp;&nbsp;&nbsp; **uw**   - under water  
   &nbsp;&nbsp;&nbsp;&nbsp; **vo**   - volodnikov  
   &nbsp;&nbsp;&nbsp;&nbsp; **yl**   - young lady  
   
   &nbsp;&nbsp;&nbsp;&nbsp; Also, every file which refers to specific game level is prefixed with 3 letters of abbreviated lavel name eg.: pyr_, pru_...  

### Importing 3do model
   1. Go to `File > Import > Import Idiana Jones IM model (.3do)`
   2. In the opened dialog, set the path to the folder containing material files (.mat) of model.  
   (Bottom left, `Materials folder` property under `Import 3DO` section)  
   *Note: What material files are used by model can be viewed under `MATERIALS` section at the begining of the `3do` file.*
   
   3. Select the `*.3do` model file and click `Import 3DO`   
   *Note: If you are later planning to export the model make sure that  
   the property `Preserve Mesh Hierarchy` is turned on, so the animations won't break in the game.*
   
### Exporting 3do model
   1. Go to `File > Export > Import Idiana Jones IM model (.3do)`
   2. Select path, name the file and click `Export 3DO`  
   *Note: The file name must not be longer then 64 characters. See section [File naming convention](#file-naming-convention).*
   
### Importing animation
   1. First import 3do model that animation is for.   
   *Note: Which key file belongs to which 3do model cannot be figured out easely because one model can have many animations.
   One thing to do is opening puppet file (`.pup`) located in misc/pup folder and see which animations belongs to same game "actor". Another way is to open up `3do` and `key` file and see if `3do` file contains all mesh names used by `key` file.*
   
   1. Go to `File > Import > Import Idiana Jones IM animation (.key)`
   2. Select the `*.key` file and click `Import KEY`
   
### Exporting animation
   1. Go to `File > Export > Import Idiana Jones IM animation (.key)`
   2. (Optional) Change properties of the `Export KEY` section (bottom left)
   3. Select path, name the file and click `Export KEY`  
   *Note: The file name must not be longer then 64 characters. See section [File naming convention](#file-naming-convention).*

### Importing material
   1. Go to `File > Import > Import Idiana Jones IM material (.mat)`
   3. Select the `*.mat` file and click `Import MAT`      
